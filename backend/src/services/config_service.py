"""
Cloud Configuration Synchronization Service.
Handles canonical JSON serialization, cryptographic SHA-256 checksums,
configuration version incrementing, immutable version archival,
out-of-sync drift detection, device sync acknowledgments, and rollbacks.
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import json
import hashlib
from sqlalchemy.orm import Session
from src.db.base import utc_now
from src.db.models.device import Device, DeviceModule
from src.db.models.config import DeviceConfig, ConfigurationVersion
from src.db.models.audit import AuditLog
from src.db.models.telemetry import DeviceLog
from src.db.models.user import User
from src.core.exceptions.errors import NotFoundException, BadRequestException
from src.api.v1.configs.schemas import (
    DeviceConfigPayload,
    ConfigSyncAckRequest,
    ConfigSyncAckResponse,
    ConfigUpdateRequest,
    ConfigDiffResponse,
)

# Simulated in-memory MQTT message bus for tracking published config events in testing and runtime
SIMULATED_MQTT_CONFIG_BUS: Dict[str, Dict[str, Any]] = {}


def compute_canonical_checksum(payload: Dict[str, Any]) -> Tuple[str, str]:
    """
    Produce canonical deterministic JSON string and calculate its SHA-256 hex digest.
    Keys are sorted recursively and compact separators (no whitespace) are enforced.
    """
    canonical_str = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
    return canonical_str, checksum


def build_device_composite_payload(device: Device) -> Dict[str, Any]:
    """
    Assemble the complete composite configuration dictionary for a given device
    from its hardware modules, slot assignments, and active settings.
    """
    # 1. Base module flags and configs
    modules_map: Dict[str, bool] = {}
    module_configs: Dict[str, Any] = {}
    for mod in device.modules:
        modules_map[mod.module_code] = mod.is_enabled
        if mod.configuration:
            module_configs[mod.module_code] = mod.configuration

    # 2. Existing config payload or defaults
    existing_payload = device.config.config_payload if device.config and device.config.config_payload else {}
    telemetry_cfg = existing_payload.get("telemetry", {
        "heartbeat_interval_sec": 60,
        "log_level": "INFO",
        "offline_threshold_sec": 300,
    })
    settings_cfg = existing_payload.get("settings", {})

    # Preserve any top-level settings like reader_mode for RFID
    for k in ["reader_mode", "buzzer_beep_ms", "offline_cache_enabled"]:
        if k in existing_payload and k not in settings_cfg:
            settings_cfg[k] = existing_payload[k]

    # 3. Slots mapping if vending machine
    slots_data: Optional[List[Dict[str, Any]]] = None
    if device.device_type and device.device_type.code == "VENDING_MACHINE":
        if device.slots and len(device.slots) > 0:
            slots_data = []
            for slot in sorted(device.slots, key=lambda s: s.slot_number):
                prod_code = slot.product.product_code if slot.product else None
                prod_price = slot.override_price if slot.override_price is not None else (slot.product.price if slot.product else 0)
                slots_data.append({
                    "slot": slot.slot_number,
                    "code": slot.slot_code,
                    "product": prod_code,
                    "price": prod_price,
                    "pin": slot.motor_pin,
                    "capacity": slot.capacity,
                    "stock": slot.current_stock,
                    "is_active": slot.is_active,
                })
        elif "slots" in existing_payload:
            slots_data = existing_payload["slots"]

    composite: Dict[str, Any] = {
        "device_id": device.device_id,
        "product_type": device.device_type.code if device.device_type else "UNKNOWN",
        "config_version": device.current_config_version,
        "modules": modules_map,
        "module_configs": module_configs,
        "telemetry": telemetry_cfg,
        "settings": settings_cfg,
    }

    if slots_data is not None:
        composite["slots"] = slots_data

    return composite


def sync_device_config_record(
    db: Session,
    device: Device,
    raw_payload: Dict[str, Any],
    change_reason: str,
    actor_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> DeviceConfig:
    """
    Increments device configuration version, calculates SHA-256 checksum,
    updates active DeviceConfig (marking is_synced=False), archives immutable
    ConfigurationVersion, records an audit log, and publishes to MQTT.
    """
    new_version = device.current_config_version + 1
    device.current_config_version = new_version

    # Ensure metadata fields are synchronized
    raw_payload["device_id"] = device.device_id
    raw_payload["config_version"] = new_version
    raw_payload["updated_at"] = utc_now().isoformat()

    _, checksum = compute_canonical_checksum(raw_payload)

    # 1. Update or create active DeviceConfig
    if device.config:
        device.config.active_version = new_version
        device.config.config_payload = raw_payload
        device.config.checksum = checksum
        device.config.is_synced = False
        device.config.last_synced_at = None
        dev_config = device.config
    else:
        dev_config = DeviceConfig(
            device_id=device.id,
            client_id=device.client_id,
            active_version=new_version,
            config_payload=raw_payload,
            checksum=checksum,
            is_synced=False,
        )
        db.add(dev_config)

    # 2. Archive immutable ConfigurationVersion
    version_archive = ConfigurationVersion(
        device_id=device.id,
        client_id=device.client_id,
        version_number=new_version,
        config_payload=raw_payload,
        checksum=checksum,
        change_reason=change_reason,
        created_by_user_id=actor_user_id,
    )
    db.add(version_archive)

    # 3. Create Audit Log
    db.add(AuditLog(
        client_id=device.client_id,
        user_id=actor_user_id,
        action="CONFIG_VERSION_BUMPED",
        entity_type="DEVICE_CONFIG",
        entity_id=device.id,
        new_state={
            "device_id": device.device_id,
            "version": new_version,
            "checksum": checksum,
            "change_reason": change_reason,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.commit()
    db.refresh(device)
    db.refresh(dev_config)

    # 4. Dispatch simulated MQTT config message
    publish_config_to_mqtt(device.device_id, raw_payload, checksum)

    return dev_config


def publish_config_to_mqtt(device_id: str, payload: Dict[str, Any], checksum: str) -> None:
    """
    Publish configuration payload to device MQTT topic: devices/{device_id}/config
    Retains latest config for asynchronous edge node pickup.
    """
    topic = f"devices/{device_id}/config"
    SIMULATED_MQTT_CONFIG_BUS[device_id] = {
        "topic": topic,
        "payload": payload,
        "checksum": checksum,
        "version": payload.get("config_version"),
        "published_at": utc_now().isoformat(),
    }


def get_latest_mqtt_config_message(device_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve the most recent MQTT config distribution for testing."""
    return SIMULATED_MQTT_CONFIG_BUS.get(device_id)


def update_device_config(
    db: Session,
    device_id: str,
    update_req: ConfigUpdateRequest,
    actor_user: Optional[User] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> DeviceConfig:
    """
    Update configuration attributes for a device and bump its revision.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    # Assemble base payload
    payload = build_device_composite_payload(device)

    # Apply modules update
    if update_req.modules is not None:
        payload["modules"] = payload.get("modules", {})
        for mod_code, is_on in update_req.modules.items():
            payload["modules"][mod_code] = is_on
            # Also update DeviceModule table
            mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code=mod_code).first()
            if mod:
                mod.is_enabled = is_on
            else:
                db.add(DeviceModule(device_id=device.id, module_code=mod_code, is_enabled=is_on))

    # Apply module_configs update
    if update_req.module_configs is not None:
        payload["module_configs"] = payload.get("module_configs", {})
        payload["module_configs"].update(update_req.module_configs)

    # Apply slots update
    if update_req.slots is not None:
        payload["slots"] = update_req.slots
        from src.db.models.vending import MachineSlot
        for s_data in update_req.slots:
            slot_num = s_data.get("slot")
            if slot_num is not None:
                mslot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=slot_num).first()
                if mslot:
                    if "price" in s_data:
                        mslot.override_price = s_data["price"]
                    if "pin" in s_data:
                        mslot.motor_pin = s_data["pin"]
                    if "capacity" in s_data:
                        mslot.capacity = s_data["capacity"]
                    if "stock" in s_data:
                        mslot.current_stock = s_data["stock"]
                    if "is_active" in s_data:
                        mslot.is_active = s_data["is_active"]

    # Apply telemetry update
    if update_req.telemetry is not None:
        payload["telemetry"] = payload.get("telemetry", {})
        payload["telemetry"].update(update_req.telemetry)

    # Apply generic settings update
    if update_req.settings is not None:
        payload["settings"] = payload.get("settings", {})
        payload["settings"].update(update_req.settings)

    actor_id = actor_user.id if actor_user else None
    return sync_device_config_record(
        db=db,
        device=device,
        raw_payload=payload,
        change_reason=update_req.change_reason,
        actor_user_id=actor_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def rollback_device_config(
    db: Session,
    device_id: str,
    target_version: int,
    change_reason: Optional[str] = None,
    actor_user: Optional[User] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> DeviceConfig:
    """
    Rollback device configuration to a previously archived version number.
    Preserves version immutability by creating a new forward version holding the target payload.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    historical_record = db.query(ConfigurationVersion).filter(
        ConfigurationVersion.device_id == device.id,
        ConfigurationVersion.version_number == target_version,
    ).first()

    if not historical_record:
        raise NotFoundException(f"Configuration version v{target_version} for device", device_id)

    # Clone historical payload
    restored_payload = dict(historical_record.config_payload)

    # Sync module records to match restored payload if modules specified
    if "modules" in restored_payload:
        for mod_code, is_on in restored_payload["modules"].items():
            mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code=mod_code).first()
            if mod:
                mod.is_enabled = is_on
            else:
                db.add(DeviceModule(device_id=device.id, module_code=mod_code, is_enabled=is_on))

    reason = change_reason or f"Administrative rollback to revision v{target_version}"
    actor_id = actor_user.id if actor_user else None

    return sync_device_config_record(
        db=db,
        device=device,
        raw_payload=restored_payload,
        change_reason=reason,
        actor_user_id=actor_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )


def process_device_ack(
    db: Session,
    device: Device,
    ack_req: ConfigSyncAckRequest,
) -> ConfigSyncAckResponse:
    """
    Process an acknowledgment published by an ESP32 hardware device after
    writing the new configuration to Non-Volatile Storage (NVS).
    Enforces strict checksum and version matching.
    """
    now = utc_now()

    # 1. Check version match
    if ack_req.applied_version != device.current_config_version:
        db.add(DeviceLog(
            device_id=device.id,
            client_id=device.client_id,
            log_level="WARN",
            subsystem="CONFIG",
            message=(
                f"Config ACK version mismatch: edge reported v{ack_req.applied_version}, "
                f"cloud expected v{device.current_config_version}."
            ),
            log_data={"error_code": "VERSION_MISMATCH"},
            recorded_at=now,
        ))
        db.commit()
        return ConfigSyncAckResponse(
            device_id=device.device_id,
            status="VERSION_MISMATCH",
            is_synced=False,
            active_version=device.current_config_version,
            acknowledged_at=now,
            message=(
                f"Rejected: Device applied version {ack_req.applied_version}, "
                f"but cloud active version is {device.current_config_version}."
            ),
        )

    # 2. Check checksum match
    cloud_checksum = device.config.checksum if device.config else ""
    if ack_req.checksum.lower().strip() != cloud_checksum.lower().strip():
        if device.config:
            device.config.is_synced = False
        db.add(DeviceLog(
            device_id=device.id,
            client_id=device.client_id,
            log_level="ERROR",
            subsystem="CONFIG",
            message=(
                f"Config ACK checksum mismatch on v{ack_req.applied_version}: "
                f"edge computed '{ack_req.checksum}', cloud expected '{cloud_checksum}'."
            ),
            log_data={"error_code": "CHECKSUM_MISMATCH"},
            recorded_at=now,
        ))
        db.commit()
        return ConfigSyncAckResponse(
            device_id=device.device_id,
            status="CHECKSUM_MISMATCH",
            is_synced=False,
            active_version=device.current_config_version,
            acknowledged_at=now,
            message=(
                f"Rejected: Calculated SHA-256 checksum '{ack_req.checksum}' does not match "
                f"cloud canonical checksum '{cloud_checksum}'."
            ),
        )

    # 3. Check error status reported by edge
    if ack_req.status.upper() != "SUCCESS":
        if device.config:
            device.config.is_synced = False
        db.add(DeviceLog(
            device_id=device.id,
            client_id=device.client_id,
            log_level="ERROR",
            subsystem="CONFIG",
            message=f"Device reported configuration error: {ack_req.error_message or 'Unknown edge failure'}",
            log_data={"error_code": ack_req.status},
            recorded_at=now,
        ))
        db.commit()
        return ConfigSyncAckResponse(
            device_id=device.device_id,
            status="ERROR",
            is_synced=False,
            active_version=device.current_config_version,
            acknowledged_at=now,
            message=f"Device reported error during config application: {ack_req.error_message}",
        )

    # 4. Successful sync
    if device.config:
        device.config.is_synced = True
        device.config.last_synced_at = now

    device.is_online = True
    device.last_heartbeat_at = now

    db.add(DeviceLog(
        device_id=device.id,
        client_id=device.client_id,
        log_level="INFO",
        subsystem="CONFIG",
        message=f"Configuration v{ack_req.applied_version} successfully synchronized and committed to NVS flash.",
        recorded_at=now,
    ))
    db.commit()

    return ConfigSyncAckResponse(
        device_id=device.device_id,
        status="ACKNOWLEDGED",
        is_synced=True,
        active_version=device.current_config_version,
        acknowledged_at=now,
        message=f"Configuration revision v{ack_req.applied_version} synchronized successfully.",
    )


def diff_configurations(
    db: Session,
    device_id: str,
    base_version_num: int,
    target_version_num: int,
) -> ConfigDiffResponse:
    """
    Compare two configuration revisions for a device and return field-level differences.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    v1 = db.query(ConfigurationVersion).filter(
        ConfigurationVersion.device_id == device.id,
        ConfigurationVersion.version_number == base_version_num,
    ).first()
    if not v1:
        raise NotFoundException(f"Base config revision v{base_version_num}", device_id)

    v2 = db.query(ConfigurationVersion).filter(
        ConfigurationVersion.device_id == device.id,
        ConfigurationVersion.version_number == target_version_num,
    ).first()
    if not v2:
        raise NotFoundException(f"Target config revision v{target_version_num}", device_id)

    diffs: Dict[str, Any] = {}
    p1 = v1.config_payload
    p2 = v2.config_payload

    all_keys = set(p1.keys()).union(set(p2.keys()))
    for key in all_keys:
        val1 = p1.get(key)
        val2 = p2.get(key)
        if val1 != val2:
            diffs[key] = {
                f"v{base_version_num}": val1,
                f"v{target_version_num}": val2,
            }

    return ConfigDiffResponse(
        device_id=device.device_id,
        base_version=base_version_num,
        target_version=target_version_num,
        has_drift=len(diffs) > 0,
        differences=diffs,
    )
