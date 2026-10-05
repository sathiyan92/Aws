"""
Device Gateway API endpoints.
Handles ESP32 physical hardware authentication, cryptographic handshakes,
heartbeat telemetry ingestion, diagnostic logs, and offline sweeps.
"""
from typing import List, Optional
from datetime import datetime, timezone, timedelta
import hashlib
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.base import utc_now
from src.db.models.device import Device, DeviceCredential
from src.db.models.telemetry import DeviceHeartbeat, DeviceLog
from src.db.models.audit import AuditLog
from src.core.config.settings import settings
from src.core.security.tokens import create_device_session_token
from src.core.security.dependencies import (
    get_authenticated_device,
    TenantContext,
    require_roles,
)
from src.core.exceptions.errors import (
    DeviceAuthFailedException,
    HardwareMismatchException,
    CredentialRevokedException,
    ForbiddenException,
)
from src.api.v1.devices.gateway_schemas import (
    DeviceAuthRequest,
    DeviceAuthResponse,
    MQTTConnectionDetails,
    MQTTTopicMap,
    HeartbeatRequest,
    HeartbeatResponse,
    DeviceLogBatchRequest,
    DeviceLogBatchResponse,
    OfflineSweepResponse,
)

router = APIRouter(prefix="/device-gateway", tags=["Device Authentication & Telemetry Gateway"])


@router.post("/authenticate", response_model=DeviceAuthResponse)
def authenticate_device(
    payload: DeviceAuthRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    [Edge Device Handshake] Authenticate an ESP32 hardware node.
    Verifies:
    1. Device exists and is not suspended.
    2. Device token matches stored SHA-256 hash.
    3. Hardware tuple (eFuse Chip ID and MAC Address) strictly matches factory registration.
    4. Credential is not revoked.
    Returns:
    - 24-hour device session token (JWT with role DEVICE_CLIENT).
    - Device-scoped MQTT broker topics and connection parameters.
    """
    # 1. Lookup Device
    device = db.query(Device).filter(Device.device_id == payload.device_id).first()
    if not device:
        raise DeviceAuthFailedException(f"Device '{payload.device_id}' is not registered on this platform.")

    if device.status == "SUSPENDED":
        raise ForbiddenException(f"Device '{payload.device_id}' is suspended. Please contact platform operations.")

    # 2. Lookup Credential
    cred = db.query(DeviceCredential).filter(DeviceCredential.device_id == device.id).first()
    if not cred or cred.is_revoked:
        raise CredentialRevokedException(f"Credential for device '{payload.device_id}' is missing or has been revoked.")

    if cred.expires_at and cred.expires_at < utc_now():
        raise CredentialRevokedException("Device credential has expired.")

    # 3. Verify Token Hash
    computed_hash = hashlib.sha256(payload.device_token.encode()).hexdigest()
    if computed_hash != cred.token_hash:
        raise DeviceAuthFailedException("Invalid device secret token.")

    # 4. Verify Physical Hardware Tuple (Anti-cloning protection)
    if payload.chip_id.strip().upper() != device.chip_id.strip().upper() or \
       payload.mac_address.strip().upper() != device.mac_address.strip().upper():
        raise HardwareMismatchException(
            f"Hardware identity mismatch on '{device.device_id}'. "
            f"Presented MAC ({payload.mac_address}) or Chip ID ({payload.chip_id}) does not match factory records."
        )

    # 5. Generate Signed Device Session JWT
    session_token = create_device_session_token(
        device_id=device.device_id,
        device_pk=device.id,
        client_id=device.client_id,
    )

    # 6. Update Device Online Status & Timestamps
    now = utc_now()
    device.is_online = True
    device.last_heartbeat_at = now
    if payload.firmware_version:
        device.current_firmware_version = payload.firmware_version
    cred.last_used_at = now

    # 7. Audit Connection Event
    client_ip = request.client.host if request.client else "127.0.0.1"
    db.add(AuditLog(
        client_id=device.client_id,
        action="DEVICE_AUTHENTICATED",
        entity_type="DEVICE",
        entity_id=device.id,
        new_state={
            "device_id": device.device_id,
            "mac_address": payload.mac_address,
            "chip_id": payload.chip_id,
            "boot_count": payload.boot_count,
            "firmware_version": payload.firmware_version,
        },
        ip_address=client_ip,
        user_agent="ESP32-Firmware/1.0",
    ))
    db.commit()

    # 8. Return Session Token and Device-Scoped MQTT Details
    mqtt_details = MQTTConnectionDetails(
        broker_uri=f"mqtts://{request.url.hostname or 'localhost'}:8883",
        port=8883,
        client_id=device.device_id,
        topics=MQTTTopicMap(
            heartbeat=f"devices/{device.device_id}/heartbeat",
            telemetry=f"devices/{device.device_id}/telemetry",
            config=f"devices/{device.device_id}/config",
            commands=f"devices/{device.device_id}/commands",
            ota=f"devices/{device.device_id}/ota",
        ),
    )

    return DeviceAuthResponse(
        session_token=session_token,
        token_type="Bearer",
        expires_in_seconds=86400,
        device_id=device.device_id,
        client_id=device.client_id,
        product_type=device.device_type.code,
        active_config_version=device.current_config_version,
        mqtt=mqtt_details,
        server_time=now,
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
def report_device_heartbeat(
    payload: HeartbeatRequest,
    device: Device = Depends(get_authenticated_device),
    db: Session = Depends(get_db),
):
    """
    [Edge Telemetry Ingest] Periodic health and status ping from ESP32 node.
    Updates online status, records time-series metrics, and detects configuration drift.
    """
    now = utc_now()

    # Update active device state
    device.is_online = True
    device.last_heartbeat_at = now
    device.current_firmware_version = payload.current_firmware_version

    # Check configuration version alignment
    config_in_sync = (device.current_config_version == payload.current_config_version)

    # Insert time-series heartbeat record
    heartbeat = DeviceHeartbeat(
        device_id=device.id,
        client_id=device.client_id,
        status="ONLINE",
        current_firmware_version=payload.current_firmware_version,
        current_config_version=payload.current_config_version,
        uptime_seconds=payload.uptime_seconds,
        free_heap_bytes=payload.free_heap_bytes,
        wifi_rssi=payload.wifi_rssi,
        ip_address=payload.ip_address,
        active_errors=payload.active_errors,
        recorded_at=now,
    )
    db.add(heartbeat)
    db.commit()

    return HeartbeatResponse(
        status="acknowledged",
        cloud_time=now,
        config_in_sync=config_in_sync,
        active_config_version=device.current_config_version,
        pending_commands_count=0,
    )


@router.post("/logs", response_model=DeviceLogBatchResponse)
def ingest_device_logs(
    payload: DeviceLogBatchRequest,
    device: Device = Depends(get_authenticated_device),
    db: Session = Depends(get_db),
):
    """
    [Edge Diagnostic Ingest] Flush diagnostic or error logs from edge node to cloud.
    """
    now = utc_now()
    ingested = 0

    for item in payload.logs:
        log_entry = DeviceLog(
            device_id=device.id,
            client_id=device.client_id,
            log_level=item.log_level.upper(),
            subsystem=item.subsystem.upper(),
            message=item.message,
            log_data=item.log_data,
            recorded_at=item.timestamp or now,
        )
        db.add(log_entry)
        ingested += 1

    db.commit()
    return DeviceLogBatchResponse(status="success", ingested_count=ingested)


@router.post("/offline-check", response_model=OfflineSweepResponse)
def sweep_stale_devices_offline(
    threshold_seconds: int = Query(120, description="Seconds without heartbeat before marking offline"),
    db: Session = Depends(get_db),
):
    """
    [Fleet Health Worker] Mark devices as OFFLINE if no heartbeat has been received
    within the threshold window.
    """
    now = utc_now()
    cutoff = now - timedelta(seconds=threshold_seconds)

    stale_devices = db.query(Device).filter(
        Device.is_online == True,
        (Device.last_heartbeat_at == None) | (Device.last_heartbeat_at < cutoff),
    ).all()

    offline_ids = []
    for d in stale_devices:
        d.is_online = False
        offline_ids.append(d.device_id)

    db.commit()

    return OfflineSweepResponse(
        checked_at=now,
        threshold_seconds=threshold_seconds,
        devices_marked_offline=len(offline_ids),
        offline_device_ids=offline_ids,
    )
