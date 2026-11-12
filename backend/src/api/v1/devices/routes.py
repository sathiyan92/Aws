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
    DeviceUpdateHardwareRequest,
    DeviceDeleteResponse,
    DeviceWiFiUpdateRequest,
    DeviceWiFiResponse,
    DiscoveredHardwareResponse,
    DiscoveredHardwareListResponse,
    ClaimDiscoveredHardwareRequest,
)
from src.db.base import utc_now

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
        provisioning_token=getattr(device, "provisioning_token", None),
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
        device_token=payload.device_token,
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



@router.get("/discovery-queue", response_model=DiscoveredHardwareListResponse)
def list_discovered_hardware(
    db: Session = Depends(get_db),
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN", "MANUFACTURER_SUPPORT")),
):
    """
    [Manufacturer Only] List all unassigned ESP32 hardware boards waiting to be claimed.
    """
    from src.db.models.device import DiscoveredHardware
    items = db.query(DiscoveredHardware).order_by(DiscoveredHardware.last_seen_at.desc()).all()
    return DiscoveredHardwareListResponse(
        total=len(items),
        items=[
            DiscoveredHardwareResponse(
                id=item.id,
                mac_address=item.mac_address,
                chip_id=item.chip_id,
                ip_address=item.ip_address,
                firmware_version=item.firmware_version,
                suggested_device_id=item.suggested_device_id,
                last_seen_at=item.last_seen_at,
                created_at=item.created_at,
            )
            for item in items
        ]
    )


@router.post("/discovery-queue/claim", response_model=DeviceResponse)
def claim_discovered_hardware(
    payload: ClaimDiscoveredHardwareRequest,
    request: Request,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
):
    """
    [Manufacturer Only] Claim a discovered ESP32 hardware board, bind its MAC address,
    and assign it a permanent Machine ID (e.g. VM-000005) chosen by the operator online.
    """
    from src.db.models.device import DiscoveredHardware, Device, DeviceType, DeviceCredential
    from src.db.models.client import Client
    from src.db.models.vending import Product, MachineSlot
    from src.db.models.config import DeviceConfig
    from src.core.exceptions.errors import BadRequestException
    import hashlib

    clean_mac = payload.mac_address.strip().upper()
    target_id = payload.device_id.strip()

    # Find the discovery record
    disc = db.query(DiscoveredHardware).filter(DiscoveredHardware.mac_address.ilike(clean_mac)).first()
    chip_id = disc.chip_id if disc and disc.chip_id else f"CHIP-{target_id}"

    # Check if a device with this target_id already exists
    existing_dev = db.query(Device).filter(Device.device_id == target_id).first()
    if existing_dev:
        # Check if MAC matches or is placeholder
        placeholder_macs = {'', 'AUTO', 'GENERIC', 'PENDING', 'PENDING_BINDING', '00:00:00:00:00:00'}
        if existing_dev.mac_address and existing_dev.mac_address.strip().upper() not in placeholder_macs and existing_dev.mac_address.strip().upper() != clean_mac:
            raise BadRequestException(f"Machine ID '{target_id}' is already assigned to MAC '{existing_dev.mac_address}'. Choose a different ID or edit that machine first.")
        # Bind this physical MAC to the existing device!
        existing_dev.mac_address = clean_mac
        existing_dev.chip_id = chip_id
        existing_dev.status = "ACTIVE"
        device = existing_dev
    else:
        # Determine client and product family
        client = None
        if payload.client_id:
            client = db.query(Client).filter(Client.id == payload.client_id).first()
        if not client:
            client = db.query(Client).first()

        dev_type = db.query(DeviceType).filter_by(code=payload.device_type_code or "VENDING_MACHINE").first()
        if not dev_type:
            dev_type = db.query(DeviceType).first()

        device = Device(
            device_id=target_id,
            client_id=client.id if client else None,
            device_type_id=dev_type.id,
            hardware_id=f"HW-{target_id}",
            chip_id=chip_id,
            mac_address=clean_mac,
            factory_serial=f"SN-{target_id}",
            status="ACTIVE",
            is_online=True,
            last_heartbeat_at=utc_now(),
            current_firmware_version=disc.firmware_version if disc and disc.firmware_version else "v2.2.0-razorpay-ota",
            current_config_version=1,
        )
        db.add(device)
        db.flush()

        # Add credential
        token_val = f"dev_token_{device.device_id}"
        cred = DeviceCredential(
            device_id=device.id,
            auth_type="TOKEN",
            token_hash=hashlib.sha256(token_val.encode()).hexdigest(),
        )
        db.add(cred)

        # Slot 1 & Config
        prod = db.query(Product).filter_by(client_id=client.id).first() if client else None
        slot = MachineSlot(
            device_id=device.id,
            client_id=client.id if client else None,
            slot_number=1,
            slot_code=f"SLOT-{device.device_id}-1",
            product_id=prod.id if prod else None,
            capacity=50,
            current_stock=20,
            is_active=True,
        )
        db.add(slot)
        import json
        cfg_payload = {"settings": {"current_stock": 20, "stock_management_enabled": True}}
        checksum = hashlib.sha256(json.dumps(cfg_payload, sort_keys=True).encode()).hexdigest()
        cfg = DeviceConfig(
            device_id=device.id,
            client_id=device.client_id,
            active_version=1,
            config_payload=cfg_payload,
            checksum=checksum,
            is_synced=True,
        )
        db.add(cfg)

    # Remove from discovery queue
    if disc:
        db.delete(disc)

    db.commit()
    db.refresh(device)
    return serialize_device(device)


@router.delete("/discovery-queue/{identifier}")
def dismiss_discovered_hardware(
    identifier: str,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
):
    """
    [Manufacturer Only] Dismiss or remove an item from the Discovery Queue.
    """
    from src.db.models.device import DiscoveredHardware
    disc = db.query(DiscoveredHardware).filter(
        (DiscoveredHardware.id == identifier) | (DiscoveredHardware.mac_address.ilike(identifier.strip()))
    ).first()
    if disc:
        mac = disc.mac_address
        db.delete(disc)
        db.commit()
        return {"status": "dismissed", "mac_address": mac}
    return {"status": "not_found", "message": f"Discovered hardware '{identifier}' not found."}


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


@router.put("/{device_id}", response_model=DeviceResponse)
def update_device_hardware_details(
    device_id: str,
    payload: DeviceUpdateHardwareRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Update physical hardware details, board revision, MAC address,
    chip ID, factory serial, firmware version, or operational status.
    """
    device = device_service.update_device_hardware(
        db=db,
        device_id=device_id,
        device_id_new=payload.device_id,
        hardware_id=payload.hardware_id,
        chip_id=payload.chip_id,
        mac_address=payload.mac_address,
        factory_serial=payload.factory_serial,
        status=payload.status,
        current_firmware_version=payload.current_firmware_version,
        actor_user=context.user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return serialize_device(device)


@router.patch("/{device_id}", response_model=DeviceResponse)
def patch_device_hardware_details(
    device_id: str,
    payload: DeviceUpdateHardwareRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """[Manufacturer Only] Partial update for hardware details (alias for PUT)."""
    return update_device_hardware_details(
        device_id=device_id,
        payload=payload,
        request=request,
        context=context,
        db=db,
    )


@router.delete("/{device_id}", response_model=DeviceDeleteResponse)
def delete_device(
    device_id: str,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Permanently delete a physical device and cascades all credentials,
    modules, slot mappings, and configurations.
    """
    res = device_service.delete_device(
        db=db,
        device_id=device_id,
        actor_user=context.user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return DeviceDeleteResponse(**res)


@router.get("/{device_id}/wifi", response_model=DeviceWiFiResponse)
def get_device_wifi_configuration(
    device_id: str,
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Retrieve current Wi-Fi configuration metadata for a device.
    Authorized for Manufacturer operations and Client/Vendor administrators (scoped to their tenant).
    """
    device = device_service.get_device_by_id_or_device_id(
        db=db,
        identifier=device_id,
        context=context,
    )
    context.assert_device_access(device)
    res = device_service.get_device_wifi(db=db, device=device)
    return DeviceWiFiResponse(**res)


@router.put("/{device_id}/wifi", response_model=DeviceWiFiResponse)
def update_device_wifi_configuration(
    device_id: str,
    payload: DeviceWiFiUpdateRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Update target Wi-Fi SSID and password for a device.
    Allows Manufacturer Operations and Client Vendors to remotely change device Wi-Fi credentials.
    Bumps configuration version and queues sync to ESP32 Flash NVS.
    """
    device = device_service.get_device_by_id_or_device_id(
        db=db,
        identifier=device_id,
        context=context,
    )
    context.assert_device_access(device)
    res = device_service.update_device_wifi(
        db=db,
        device=device,
        wifi_ssid=payload.wifi_ssid,
        wifi_password=payload.wifi_password,
        actor_user=context.user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return DeviceWiFiResponse(**res)


@router.post("/{device_id}/wifi", response_model=DeviceWiFiResponse)
def post_device_wifi_configuration(
    device_id: str,
    payload: DeviceWiFiUpdateRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """POST alias for updating Wi-Fi credentials."""
    return update_device_wifi_configuration(
        device_id=device_id,
        payload=payload,
        request=request,
        context=context,
        db=db,
    )

