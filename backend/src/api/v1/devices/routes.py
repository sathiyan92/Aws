"""
Device Fleet Management API endpoints.
Provides device registration, client assignment, module toggles, and multi-tenant fleet querying.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.device import Device, DeviceType, DeviceModule
from src.core.security.dependencies import (
    TenantContext,
    get_tenant_context,
    require_roles,
)
from src.services import device_service
from src.api.v1.devices.schemas import (
    DeviceRegisterRequest,
    DeviceAssignRequest,
    DeviceModuleToggleRequest,
    DeviceResponse,
    DeviceListResponse,
    DeviceTypeResponse,
    DeviceModuleSchema,
)

router = APIRouter(prefix="/devices", tags=["Device Fleet Management"])


def serialize_device(device: Device) -> DeviceResponse:
    """Format SQLAlchemy Device model into Pydantic DeviceResponse."""
    modules_list = [
        DeviceModuleSchema(
            module_code=m.module_code,
            is_enabled=m.is_enabled,
            configuration=m.configuration,
        )
        for m in device.modules
    ]
    return DeviceResponse(
        id=device.id,
        device_id=device.device_id,
        client_id=device.client_id,
        client_name=device.client.name if device.client else None,
        device_type_code=device.device_type.code,
        device_type_name=device.device_type.name,
        hardware_id=device.hardware_id,
        chip_id=device.chip_id,
        mac_address=device.mac_address,
        factory_serial=device.factory_serial,
        status=device.status,
        is_online=device.is_online,
        current_firmware_version=device.current_firmware_version,
        current_config_version=device.current_config_version,
        last_heartbeat_at=device.last_heartbeat_at,
        created_at=device.created_at,
        modules=modules_list,
        credential_auth_type=device.credentials.auth_type if device.credentials else None,
    )


@router.get("/types", response_model=List[DeviceTypeResponse])
def list_device_types(
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """List supported hardware product types."""
    types = db.query(DeviceType).all()
    return [
        DeviceTypeResponse(
            id=t.id,
            code=t.code,
            name=t.name,
            description=t.description,
            supported_modules=t.supported_modules,
        )
        for t in types
    ]


@router.post("", response_model=DeviceResponse)
def register_device(
    payload: DeviceRegisterRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Register a newly assembled ESP32 device.
    Generates permanent Device ID, unique device credentials, initial modules, and config v1.
    """
    device = device_service.register_physical_device(
        db=db,
        device_type_code=payload.device_type_code,
        hardware_id=payload.hardware_id,
        chip_id=payload.chip_id,
        mac_address=payload.mac_address,
        factory_serial=payload.factory_serial,
        initial_modules=payload.initial_modules,
        client_id=payload.client_id,
        actor_user=context.user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return serialize_device(device)


@router.get("", response_model=DeviceListResponse)
def get_fleet_devices(
    client_id: Optional[str] = Query(None, description="Optional filter by client (Manufacturer only)"),
    device_type: Optional[str] = Query(None, description="Filter by device type code"),
    status: Optional[str] = Query(None, description="Filter by status (PROVISIONED, ASSIGNED, ACTIVE)"),
    is_online: Optional[bool] = Query(None, description="Filter by online connectivity"),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    List devices with multi-tenant isolation:
    - Manufacturer Admin: Sees all devices across all tenants, can filter by client_id.
    - Client Users: Sees ONLY devices assigned to their own client_id.
    """
    devices = device_service.list_devices(
        db=db,
        context=context,
        client_id_filter=client_id,
        device_type_code=device_type,
        status_filter=status,
        is_online_filter=is_online,
    )
    return DeviceListResponse(
        total=len(devices),
        devices=[serialize_device(d) for d in devices],
    )


@router.get("/{device_id}", response_model=DeviceResponse)
def get_device_details(
    device_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Retrieve single device profile.
    Enforces tenant boundary: Client can only view devices assigned to their organization.
    """
    device = device_service.get_device_by_id_or_device_id(
        db=db,
        identifier=device_id,
        context=context,
    )
    return serialize_device(device)


@router.post("/{device_id}/assign", response_model=DeviceResponse)
def assign_device(
    device_id: str,
    payload: DeviceAssignRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Assign or reassign a device to a client organization,
    or set client_id to null to unassign back to factory inventory.
    """
    device = device_service.assign_device_to_client(
        db=db,
        device_id=device_id,
        client_id=payload.client_id,
        actor_user=context.user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return serialize_device(device)


@router.put("/{device_id}/modules", response_model=DeviceResponse)
def toggle_module(
    device_id: str,
    payload: DeviceModuleToggleRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Enable or disable a hardware feature module on a physical device.
    Automatically increments device configuration version and updates active config payload.
    """
    device_service.toggle_device_module(
        db=db,
        device_id=device_id,
        module_code=payload.module_code,
        is_enabled=payload.is_enabled,
        configuration=payload.configuration,
        actor_user=context.user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    # Refresh and return updated device
    device = device_service.get_device_by_id_or_device_id(
        db=db,
        identifier=device_id,
        context=context,
    )
    return serialize_device(device)
