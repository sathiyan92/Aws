"""
Device Lifecycle Service: provisioning, Device ID generation, client assignment,
hardware module toggles, configuration version bumping, and fleet querying.
"""
import hashlib
import json
import secrets
from datetime import timedelta
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.db.base import utc_now
from src.db.models.device import Device, DeviceType, DeviceModule, DeviceCredential
from src.db.models.config import DeviceConfig, ConfigurationVersion
from src.db.models.client import Client
from src.db.models.user import User
from src.db.models.audit import AuditLog
from src.core.security.dependencies import TenantContext
from src.core.exceptions.errors import (
    NotFoundException,
    BadRequestException,
    TenantIsolationException,
)


def generate_next_device_id(db: Session, device_type_code: str) -> str:
    """
    Generate an immutable sequential Device ID adhering to the standard:
    VENDING_MACHINE -> VM-000001, VM-000002...
    RFID_ATTENDANCE -> RFID-000001, RFID-000002...
    """
    if device_type_code == "VENDING_MACHINE":
        prefix = "VM"
    elif device_type_code == "RFID_ATTENDANCE":
        prefix = "RFID"
    else:
        prefix = device_type_code[:4].upper()

    # Query matching device IDs to find highest sequential number
    existing_ids = db.query(Device.device_id).filter(
        Device.device_id.like(f"{prefix}-%")
    ).all()

    max_num = 0
    for (dev_id,) in existing_ids:
        try:
            parts = dev_id.split("-")
            if len(parts) == 2 and parts[1].isdigit():
                num = int(parts[1])
                if num > max_num:
                    max_num = num
        except Exception:
            continue

    next_num = max_num + 1
    return f"{prefix}-{next_num:06d}"


def register_physical_device(
    db: Session,
    device_type_code: str,
    hardware_id: str,
    chip_id: str,
    mac_address: str,
    factory_serial: str,
    initial_modules: Dict[str, bool],
    client_id: Optional[str],
    actor_user: User,
    device_token: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Device:
    """
    Manufacturer provisions a newly assembled ESP32 device.
    Generates permanent Device ID, unique device authentication token, initial modules,
    and initial configuration version 1.
    """
    # 1. Validate device type
    dev_type = db.query(DeviceType).filter_by(code=device_type_code).first()
    if not dev_type:
        raise NotFoundException("DeviceType", device_type_code)

    # 2. Check for duplicate hardware identifiers
    if db.query(Device).filter_by(chip_id=chip_id).first():
        raise BadRequestException(f"Hardware conflict: Chip ID '{chip_id}' is already registered")
    if db.query(Device).filter_by(mac_address=mac_address).first():
        raise BadRequestException(f"Hardware conflict: MAC address '{mac_address}' is already registered")
    if db.query(Device).filter_by(factory_serial=factory_serial).first():
        raise BadRequestException(f"Hardware conflict: Factory serial '{factory_serial}' is already registered")

    # 3. Check client if provided
    client = None
    if client_id:
        client = db.query(Client).filter_by(id=client_id).first()
        if not client:
            raise NotFoundException("Client", client_id)

    # 4. Generate next permanent Device ID
    permanent_device_id = generate_next_device_id(db, device_type_code)

    # 5. Create Device entity
    device = Device(
        device_id=permanent_device_id,
        client_id=client.id if client else None,
        device_type_id=dev_type.id,
        hardware_id=hardware_id,
        chip_id=chip_id,
        mac_address=mac_address,
        factory_serial=factory_serial,
        status="ASSIGNED" if client else "PROVISIONED",
        is_online=False,
        current_firmware_version="v1.0.0",
        current_config_version=1,
    )
    db.add(device)
    db.flush()

    # 6. Generate cryptographic device token credential
    raw_token = device_token.strip() if device_token and device_token.strip() else f"dev_{secrets.token_hex(24)}"
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    credential = DeviceCredential(
        device_id=device.id,
        auth_type="TOKEN",
        token_hash=token_hash,
    )
    db.add(credential)
    device.provisioning_token = raw_token

    # 7. Configure hardware modules
    supported_mods = dev_type.supported_modules or []
    for mod_code in supported_mods:
        is_enabled = initial_modules.get(mod_code, False)
        db.add(DeviceModule(
            device_id=device.id,
            module_code=mod_code,
            is_enabled=is_enabled,
        ))

    # 8. Create Version 1 Configuration
    cfg_payload = {
        "device_id": device.device_id,
        "config_version": 1,
        "device_type": device_type_code,
        "modules": {mod: initial_modules.get(mod, False) for mod in supported_mods},
        "telemetry": {"heartbeat_interval_sec": 60},
    }
    payload_str = json.dumps(cfg_payload, sort_keys=True)
    checksum = hashlib.sha256(payload_str.encode()).hexdigest()

    db.add(DeviceConfig(
        device_id=device.id,
        client_id=device.client_id,
        active_version=1,
        config_payload=cfg_payload,
        checksum=checksum,
        is_synced=False,
    ))
    db.add(ConfigurationVersion(
        device_id=device.id,
        client_id=device.client_id,
        version_number=1,
        config_payload=cfg_payload,
        checksum=checksum,
        change_reason="Factory initial provisioning",
        created_by_user_id=actor_user.id,
    ))

    # 9. Audit Log
    db.add(AuditLog(
        client_id=device.client_id,
        user_id=actor_user.id,
        action="DEVICE_REGISTERED",
        entity_type="DEVICE",
        entity_id=device.id,
        new_state={
            "device_id": device.device_id,
            "device_type": device_type_code,
            "client_id": device.client_id,
            "status": device.status,
            "modules": initial_modules,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.commit()
    db.refresh(device)
    return device


def assign_device_to_client(
    db: Session,
    device_id: str,
    client_id: Optional[str],
    actor_user: User,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Device:
    """
    Assign a device to a client organization, or unassign it back to factory inventory.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    old_client_id = device.client_id
    old_status = device.status

    if client_id:
        target_client = db.query(Client).filter_by(id=client_id).first()
        if not target_client:
            raise NotFoundException("Client", client_id)
        device.client_id = target_client.id
        device.status = "ASSIGNED"
        if device.config:
            device.config.client_id = target_client.id
    else:
        device.client_id = None
        device.status = "PROVISIONED"
        if device.config:
            device.config.client_id = None

    db.add(AuditLog(
        client_id=device.client_id,
        user_id=actor_user.id,
        action="DEVICE_ASSIGNMENT_CHANGED",
        entity_type="DEVICE",
        entity_id=device.id,
        old_state={"client_id": old_client_id, "status": old_status},
        new_state={"client_id": device.client_id, "status": device.status},
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.commit()
    db.refresh(device)
    return device


def toggle_device_module(
    db: Session,
    device_id: str,
    module_code: str,
    is_enabled: bool,
    configuration: Optional[Dict[str, Any]],
    actor_user: User,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> DeviceModule:
    """
    Enable or disable a hardware feature module on a physical device.
    Automatically increments the device's configuration version and updates active config.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    # Find or create module
    module = db.query(DeviceModule).filter_by(
        device_id=device.id,
        module_code=module_code,
    ).first()

    old_enabled = module.is_enabled if module else False

    if not module:
        module = DeviceModule(
            device_id=device.id,
            module_code=module_code,
            is_enabled=is_enabled,
            configuration=configuration,
        )
        db.add(module)
    else:
        module.is_enabled = is_enabled
        if configuration is not None:
            module.configuration = configuration

    # Increment configuration version
    new_version = device.current_config_version + 1
    device.current_config_version = new_version

    # Update active device config
    if device.config:
        cfg_dict = dict(device.config.config_payload)
        modules_map = cfg_dict.get("modules", {})
        modules_map[module_code] = is_enabled
        cfg_dict["modules"] = modules_map
        cfg_dict["config_version"] = new_version

        payload_str = json.dumps(cfg_dict, sort_keys=True)
        checksum = hashlib.sha256(payload_str.encode()).hexdigest()

        device.config.active_version = new_version
        device.config.config_payload = cfg_dict
        device.config.checksum = checksum
        device.config.is_synced = False  # Pending sync to ESP32 node

        # Append to configuration version history
        db.add(ConfigurationVersion(
            device_id=device.id,
            client_id=device.client_id,
            version_number=new_version,
            config_payload=cfg_dict,
            checksum=checksum,
            change_reason=f"Module '{module_code}' set to {is_enabled}",
            created_by_user_id=actor_user.id,
        ))

    # Audit Log
    db.add(AuditLog(
        client_id=device.client_id,
        user_id=actor_user.id,
        action="MODULE_TOGGLED",
        entity_type="DEVICE_MODULE",
        entity_id=device.id,
        old_state={"module": module_code, "enabled": old_enabled},
        new_state={"module": module_code, "enabled": is_enabled, "config_version": new_version},
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.commit()
    db.refresh(module)

    # Publish updated config to MQTT distribution topic
    from src.services.config_service import publish_config_to_mqtt
    if device.config:
        publish_config_to_mqtt(device.device_id, device.config.config_payload, device.config.checksum)

    return module


def list_devices(
    db: Session,
    context: TenantContext,
    client_id_filter: Optional[str] = None,
    device_type_code: Optional[str] = None,
    status_filter: Optional[str] = None,
    is_online_filter: Optional[bool] = None,
) -> List[Device]:
    """
    List devices with strict tenant isolation.
    Manufacturer users can view all or filter by client.
    Client users are strictly restricted to their own client_id.
    """
    query = db.query(Device)

    if context.is_manufacturer:
        if client_id_filter:
            query = query.filter(Device.client_id == client_id_filter)
    else:
        # Enforce multi-tenant isolation: client user can ONLY query their assigned devices
        query = query.filter(Device.client_id == context.client_id)

    if device_type_code:
        query = query.join(DeviceType).filter(DeviceType.code == device_type_code)

    # Auto-sweep stale heartbeat devices: if heartbeat hasn't been received in 75s, mark offline
    now = utc_now()
    cutoff = now - timedelta(seconds=75)
    stale_devices = db.query(Device).filter(
        Device.is_online == True,
        Device.last_heartbeat_at != None,
        Device.last_heartbeat_at < cutoff,
    ).all()
    if stale_devices:
        for d in stale_devices:
            d.is_online = False
        db.commit()

    if status_filter:
        query = query.filter(Device.status == status_filter)

    if is_online_filter is not None:
        query = query.filter(Device.is_online == is_online_filter)

    return query.order_by(Device.created_at.desc()).all()


def get_device_by_id_or_device_id(
    db: Session,
    identifier: str,
    context: TenantContext,
) -> Device:
    """Fetch single device and assert tenant access."""
    device = db.query(Device).filter(
        (Device.device_id == identifier) | (Device.id == identifier)
    ).first()

    if not device:
        raise NotFoundException("Device", identifier)

    # Check if online device timed out
    if device.is_online and device.last_heartbeat_at:
        if (utc_now() - device.last_heartbeat_at).total_seconds() > 75:
            device.is_online = False
            db.commit()

    context.assert_device_access(device)
    return device


def update_device_hardware(
    db: Session,
    device_id: str,
    hardware_id: Optional[str] = None,
    chip_id: Optional[str] = None,
    mac_address: Optional[str] = None,
    factory_serial: Optional[str] = None,
    status: Optional[str] = None,
    current_firmware_version: Optional[str] = None,
    actor_user: Optional[User] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Device:
    """
    Update physical hardware specifications, identifiers, or operational lifecycle status.
    Asserts uniqueness for chip_id, mac_address, and factory_serial across all other devices.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    old_state = {
        "hardware_id": device.hardware_id,
        "chip_id": device.chip_id,
        "mac_address": device.mac_address,
        "factory_serial": device.factory_serial,
        "status": device.status,
        "current_firmware_version": device.current_firmware_version,
    }

    # Validate and check uniqueness of hardware identifiers
    if chip_id and chip_id != device.chip_id:
        existing = db.query(Device).filter(Device.chip_id == chip_id, Device.id != device.id).first()
        if existing:
            raise BadRequestException(f"Hardware conflict: Chip ID '{chip_id}' is already registered to device '{existing.device_id}'")
        device.chip_id = chip_id

    if mac_address and mac_address != device.mac_address:
        existing = db.query(Device).filter(Device.mac_address == mac_address, Device.id != device.id).first()
        if existing:
            raise BadRequestException(f"Hardware conflict: MAC address '{mac_address}' is already registered to device '{existing.device_id}'")
        device.mac_address = mac_address

    if factory_serial and factory_serial != device.factory_serial:
        existing = db.query(Device).filter(Device.factory_serial == factory_serial, Device.id != device.id).first()
        if existing:
            raise BadRequestException(f"Hardware conflict: Factory serial '{factory_serial}' is already registered to device '{existing.device_id}'")
        device.factory_serial = factory_serial

    if hardware_id:
        device.hardware_id = hardware_id

    if status:
        valid_statuses = {"PROVISIONED", "ASSIGNED", "ACTIVE", "MAINTENANCE", "SUSPENDED", "DECOMMISSIONED"}
        status_clean = status.strip().upper()
        if status_clean not in valid_statuses:
            raise BadRequestException(f"Invalid device status '{status}'. Allowed statuses: {', '.join(sorted(valid_statuses))}")
        device.status = status_clean

    if current_firmware_version:
        device.current_firmware_version = current_firmware_version

    new_state = {
        "hardware_id": device.hardware_id,
        "chip_id": device.chip_id,
        "mac_address": device.mac_address,
        "factory_serial": device.factory_serial,
        "status": device.status,
        "current_firmware_version": device.current_firmware_version,
    }

    if actor_user:
        db.add(AuditLog(
            client_id=device.client_id,
            user_id=actor_user.id,
            action="DEVICE_HARDWARE_UPDATED",
            entity_type="DEVICE",
            entity_id=device.id,
            old_state=old_state,
            new_state=new_state,
            ip_address=ip_address,
            user_agent=user_agent,
        ))

    db.commit()
    db.refresh(device)
    return device


def delete_device(
    db: Session,
    device_id: str,
    actor_user: Optional[User] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, str]:
    """
    Permanently delete a physical device and cascades all credentials, modules, and slot mappings.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    permanent_id = device.device_id
    client_id = device.client_id
    old_state = {
        "device_id": device.device_id,
        "hardware_id": device.hardware_id,
        "chip_id": device.chip_id,
        "mac_address": device.mac_address,
        "factory_serial": device.factory_serial,
        "status": device.status,
        "client_id": device.client_id,
    }

    if actor_user:
        db.add(AuditLog(
            client_id=client_id,
            user_id=actor_user.id,
            action="DEVICE_DELETED",
            entity_type="DEVICE",
            entity_id=permanent_id,
            old_state=old_state,
            new_state={"status": "DELETED"},
            ip_address=ip_address,
            user_agent=user_agent,
        ))

    db.delete(device)
    db.commit()

    return {
        "status": "deleted",
        "device_id": permanent_id,
        "message": f"Device '{permanent_id}' deleted successfully.",
    }

