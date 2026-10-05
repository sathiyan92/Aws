"""
Device Configuration Management and Synchronization API routes.
Provides REST endpoints for edge devices to pull configurations and publish ACKs,
and for portal administrators to update parameters, audit version history,
perform version rollbacks, and analyze version diffs.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Path, Request
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.base import utc_now
from src.db.models.device import Device
from src.db.models.config import DeviceConfig, ConfigurationVersion
from src.core.exceptions.errors import NotFoundException, ForbiddenException
from src.core.security.dependencies import (
    get_tenant_context,
    TenantContext,
    require_roles,
    get_authenticated_device,
)
from src.api.v1.configs.schemas import (
    DeviceConfigPayload,
    ConfigSyncAckRequest,
    ConfigSyncAckResponse,
    ConfigurationVersionSummary,
    ConfigUpdateRequest,
    ConfigRollbackRequest,
    ConfigDiffResponse,
)
from src.services.config_service import (
    build_device_composite_payload,
    update_device_config,
    rollback_device_config,
    process_device_ack,
    diff_configurations,
)

router = APIRouter(prefix="/devices", tags=["Cloud Configuration Synchronization"])


def _resolve_device_access(
    device_id: str,
    db: Session,
    request: Request,
) -> Device:
    """
    Helper resolving device while supporting both portal users (multi-tenant JWT)
    and hardware devices (session bearer token or device token headers).
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    # Check for device authentication headers
    x_dev_token = request.headers.get("X-Device-Token")
    auth_header = request.headers.get("Authorization")

    # If calling as an edge device
    if x_dev_token or (auth_header and "Bearer" in auth_header):
        try:
            auth_device = get_authenticated_device(
                authorization=auth_header,
                x_device_token=x_dev_token,
                x_device_id=request.headers.get("X-Device-ID"),
                db=db,
            )
            if auth_device and auth_device.id == device.id:
                return device
        except Exception:
            # Fallback to user tenant context
            pass

    return device


@router.get("/{device_id}/config", response_model=DeviceConfigPayload)
def get_device_config(
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    request: Request = None,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Retrieve active configuration payload and checksum for a target device.
    Verifies tenant ownership boundary if requested by a client user.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    composite = dict(device.config.config_payload) if (device.config and device.config.config_payload) else build_device_composite_payload(device)
    checksum = device.config.checksum if device.config else ""
    is_synced = device.config.is_synced if device.config else False
    last_synced_at = device.config.last_synced_at if device.config else None

    return DeviceConfigPayload(
        device_id=device.device_id,
        product_type=composite.get("product_type", "UNKNOWN"),
        config_version=device.current_config_version,
        checksum=checksum,
        is_synced=is_synced,
        last_synced_at=last_synced_at,
        modules=composite.get("modules", {}),
        module_configs=composite.get("module_configs", {}),
        slots=composite.get("slots"),
        telemetry=composite.get("telemetry", {}),
        settings=composite.get("settings", {}),
        updated_at=device.config.updated_at if device.config else None,
    )


@router.post("/{device_id}/config/ack", response_model=ConfigSyncAckResponse)
def acknowledge_config_sync(
    payload: ConfigSyncAckRequest,
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    db: Session = Depends(get_db),
):
    """
    [Edge Device Endpoint] Hardware node acknowledges writing new configuration into NVS.
    Verifies SHA-256 checksum and version number against cloud records.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    return process_device_ack(db=db, device=device, ack_req=payload)


@router.patch("/{device_id}/config", response_model=DeviceConfigPayload)
def update_configuration(
    payload: ConfigUpdateRequest,
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Update configuration settings on a device (e.g., slot prices, telemetry intervals).
    Automatically increments the configuration version and marks sync pending.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    updated_config = update_device_config(
        db=db,
        device_id=device_id,
        update_req=payload,
        actor_user=context.user,
    )

    composite = dict(updated_config.config_payload)

    return DeviceConfigPayload(
        device_id=device.device_id,
        product_type=composite.get("product_type", "UNKNOWN"),
        config_version=updated_config.active_version,
        checksum=updated_config.checksum,
        is_synced=updated_config.is_synced,
        last_synced_at=updated_config.last_synced_at,
        modules=composite.get("modules", {}),
        module_configs=composite.get("module_configs", {}),
        slots=composite.get("slots"),
        telemetry=composite.get("telemetry", {}),
        settings=composite.get("settings", {}),
        updated_at=updated_config.updated_at,
    )


@router.get("/{device_id}/config/history", response_model=List[ConfigurationVersionSummary])
def get_config_history(
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Retrieve full historical audit trail of all configuration revisions for a device.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    history = db.query(ConfigurationVersion).filter(
        ConfigurationVersion.device_id == device.id
    ).order_by(ConfigurationVersion.version_number.desc()).all()

    return [
        ConfigurationVersionSummary(
            id=item.id,
            device_id=device.device_id,
            version_number=item.version_number,
            checksum=item.checksum,
            change_reason=item.change_reason,
            created_by_user_id=item.created_by_user_id,
            created_at=item.created_at,
            config_payload=item.config_payload,
        )
        for item in history
    ]


@router.post("/{device_id}/config/rollback", response_model=DeviceConfigPayload)
def rollback_configuration(
    payload: ConfigRollbackRequest,
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Rollback device configuration to an earlier version.
    Generates a new incremented version containing the historical settings.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    restored_config = rollback_device_config(
        db=db,
        device_id=device_id,
        target_version=payload.target_version,
        change_reason=payload.change_reason,
        actor_user=context.user,
    )

    composite = dict(restored_config.config_payload)

    return DeviceConfigPayload(
        device_id=device.device_id,
        product_type=composite.get("product_type", "UNKNOWN"),
        config_version=restored_config.active_version,
        checksum=restored_config.checksum,
        is_synced=restored_config.is_synced,
        last_synced_at=restored_config.last_synced_at,
        modules=composite.get("modules", {}),
        module_configs=composite.get("module_configs", {}),
        slots=composite.get("slots"),
        telemetry=composite.get("telemetry", {}),
        settings=composite.get("settings", {}),
        updated_at=restored_config.updated_at,
    )


@router.get("/{device_id}/config/diff", response_model=ConfigDiffResponse)
def compare_config_versions(
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    base_version: int = Query(..., ge=1, description="Base configuration version"),
    target_version: int = Query(..., ge=1, description="Target configuration version"),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Compare two configuration revisions and return the specific key-value diffs.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    return diff_configurations(
        db=db,
        device_id=device_id,
        base_version_num=base_version,
        target_version_num=target_version,
    )
