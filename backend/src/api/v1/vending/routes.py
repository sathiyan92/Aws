"""
Vending Machine Subsystem API endpoints.
Enforces strict dynamic module policy guards on QR and Coin configurations and transactions.
"""
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Path, Query, status
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.device import Device, DeviceModule
from src.db.models.vending import Product, MachineSlot, Transaction
from src.core.exceptions.errors import NotFoundException, ForbiddenException
from src.core.security.dependencies import (
    TenantContext,
    get_tenant_context,
    require_roles,
    require_device_module,
)
from src.api.v1.vending.schemas import (
    QRSettingsResponse,
    QRSettingsUpdateRequest,
    CoinSettingsResponse,
    CoinSettingsUpdateRequest,
    VendingTransactionResponse,
    ClientFleetCapabilityItem,
    ProductCreateRequest,
    ProductUpdateRequest,
    ProductResponse,
    MachineSlotResponse,
    MachineSlotConfigureRequest,
    MachineSlotBulkConfigureRequest,
    MachineSlotRestockRequest,
)
from src.services.vending_service import (
    list_products,
    get_product,
    create_product,
    update_product,
    delete_product,
    list_machine_slots,
    configure_slot,
    bulk_configure_slots,
    restock_slot,
)

router = APIRouter(prefix="/vending", tags=["Vending Subsystem"])


def _format_product(p: Product) -> ProductResponse:
    """Helper to convert Product ORM instance into ProductResponse schema."""
    return ProductResponse(
        id=p.id,
        client_id=p.client_id,
        product_code=p.product_code,
        name=p.name,
        description=p.description,
        price=p.price,
        price_rupees=p.price / 100.0,
        image_url=p.image_url,
        is_active=p.is_active,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _format_slot(s: MachineSlot, device: Device) -> MachineSlotResponse:
    """Helper to convert MachineSlot ORM instance into MachineSlotResponse schema."""
    eff_price = s.override_price if s.override_price is not None else (s.product.price if s.product else 0)
    return MachineSlotResponse(
        id=s.id,
        device_id=device.device_id,
        slot_number=s.slot_number,
        slot_code=s.slot_code,
        product_id=s.product_id,
        product_code=s.product.product_code if s.product else None,
        product_name=s.product.name if s.product else None,
        price=eff_price,
        price_rupees=eff_price / 100.0,
        override_price=s.override_price,
        motor_pin=s.motor_pin,
        pulse_duration_ms=s.pulse_duration_ms,
        capacity=s.capacity,
        current_stock=s.current_stock,
        is_active=s.is_active,
    )


@router.get("/fleet-capabilities", response_model=List[ClientFleetCapabilityItem])
def get_client_fleet_capabilities(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Retrieve all devices assigned to the requesting client tenant with dynamic module enablement flags.
    Used by the Client Dashboard to dynamically show/hide navigation tabs and features.
    """
    query = db.query(Device)
    if not context.is_manufacturer:
        query = query.filter(Device.client_id == context.client_id)

    devices = query.all()
    results = []
    for d in devices:
        mods = {m.module_code: m.is_enabled for m in d.modules}
        results.append(ClientFleetCapabilityItem(
            device_id=d.device_id,
            product_type=d.device_type.code,
            status=d.status,
            is_online=d.is_online,
            config_version=d.current_config_version,
            firmware_version=d.current_firmware_version,
            has_qr_payment=mods.get("QR_PAYMENT", False),
            has_coin_payment=mods.get("COIN_PAYMENT", False),
            has_rfid_access=mods.get("RFID_ACCESS", False),
            modules=mods,
        ))
    return results


# ------------------------------------------------------------------------------
# QR PAYMENT ENDPOINTS (Strictly Guarded by QR_PAYMENT Module)
# ------------------------------------------------------------------------------

@router.get("/{device_id}/qr/settings", response_model=QRSettingsResponse)
def get_qr_settings(
    device: Device = Depends(require_device_module("QR_PAYMENT")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: QR_PAYMENT] Retrieve dynamic UPI QR payment settings for machine.
    Rejects with 403 MODULE_DISABLED_FOR_DEVICE if QR_PAYMENT is disabled.
    """
    qr_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="QR_PAYMENT").first()
    cfg = qr_mod.configuration or {}

    return QRSettingsResponse(
        device_id=device.device_id,
        provider=cfg.get("provider", "UPI_DYNAMIC"),
        upi_merchant_vpa=cfg.get("upi_merchant_vpa", f"pay.{device.device_id.lower()}@icici"),
        qr_timeout_seconds=cfg.get("qr_timeout_seconds", 180),
        dynamic_pricing_enabled=cfg.get("dynamic_pricing_enabled", True),
        is_active=qr_mod.is_enabled,
    )


@router.put("/{device_id}/qr/settings", response_model=QRSettingsResponse)
def update_qr_settings(
    payload: QRSettingsUpdateRequest,
    device: Device = Depends(require_device_module("QR_PAYMENT")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: QR_PAYMENT] Update dynamic UPI QR payment settings.
    Bumps device configuration version.
    """
    qr_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="QR_PAYMENT").first()
    cfg = dict(qr_mod.configuration or {})

    if payload.upi_merchant_vpa is not None:
        cfg["upi_merchant_vpa"] = payload.upi_merchant_vpa
    if payload.qr_timeout_seconds is not None:
        cfg["qr_timeout_seconds"] = payload.qr_timeout_seconds
    if payload.dynamic_pricing_enabled is not None:
        cfg["dynamic_pricing_enabled"] = payload.dynamic_pricing_enabled

    qr_mod.configuration = cfg
    device.current_config_version += 1
    if device.config:
        device.config.active_version = device.current_config_version
        device.config.is_synced = False

    db.commit()

    return QRSettingsResponse(
        device_id=device.device_id,
        provider=cfg.get("provider", "UPI_DYNAMIC"),
        upi_merchant_vpa=cfg.get("upi_merchant_vpa", f"pay.{device.device_id.lower()}@icici"),
        qr_timeout_seconds=cfg.get("qr_timeout_seconds", 180),
        dynamic_pricing_enabled=cfg.get("dynamic_pricing_enabled", True),
        is_active=qr_mod.is_enabled,
    )


@router.get("/{device_id}/qr/transactions", response_model=List[VendingTransactionResponse])
def get_qr_transactions(
    device: Device = Depends(require_device_module("QR_PAYMENT")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: QR_PAYMENT] Retrieve digital QR transaction history.
    """
    txs = db.query(Transaction).filter(
        Transaction.device_id == device.id,
        Transaction.transaction_type == "QR_VEND",
    ).order_by(Transaction.transacted_at.desc()).limit(50).all()

    return [
        VendingTransactionResponse(
            id=t.id,
            transaction_number=t.transaction_number,
            device_id=device.device_id,
            transaction_type=t.transaction_type,
            amount_in_rupees=t.amount / 100.0,
            coins_inserted=t.coins_inserted,
            change_dispensed=t.change_dispensed,
            dispense_status=t.dispense_status,
            transacted_at=t.transacted_at,
        )
        for t in txs
    ]


# ------------------------------------------------------------------------------
# COIN ACCEPTOR ENDPOINTS (Strictly Guarded by COIN_PAYMENT Module)
# ------------------------------------------------------------------------------

@router.get("/{device_id}/coins/settings", response_model=CoinSettingsResponse)
def get_coin_settings(
    device: Device = Depends(require_device_module("COIN_PAYMENT")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: COIN_PAYMENT] Retrieve electronic coin pulse acceptor configuration.
    Rejects with 403 MODULE_DISABLED_FOR_DEVICE if COIN_PAYMENT is disabled.
    """
    coin_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="COIN_PAYMENT").first()
    cfg = coin_mod.configuration or {}

    default_mappings = {"1": 100, "2": 200, "5": 500, "10": 1000}
    return CoinSettingsResponse(
        device_id=device.device_id,
        acceptor_mode=cfg.get("acceptor_mode", "PULSE_TRAIN"),
        pulse_mappings=cfg.get("pulse_mappings", default_mappings),
        debounce_ms=cfg.get("debounce_ms", 50),
        coin_escrow_enabled=cfg.get("coin_escrow_enabled", True),
        change_dispenser_fitted=cfg.get("change_dispenser_fitted", False),
    )


@router.put("/{device_id}/coins/settings", response_model=CoinSettingsResponse)
def update_coin_settings(
    payload: CoinSettingsUpdateRequest,
    device: Device = Depends(require_device_module("COIN_PAYMENT")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: COIN_PAYMENT] Update coin pulse-to-value mapping and debounce timing.
    Bumps device configuration version.
    """
    coin_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="COIN_PAYMENT").first()
    cfg = dict(coin_mod.configuration or {})

    if payload.pulse_mappings is not None:
        cfg["pulse_mappings"] = payload.pulse_mappings
    if payload.debounce_ms is not None:
        cfg["debounce_ms"] = payload.debounce_ms
    if payload.change_dispenser_fitted is not None:
        cfg["change_dispenser_fitted"] = payload.change_dispenser_fitted

    coin_mod.configuration = cfg
    device.current_config_version += 1
    if device.config:
        device.config.active_version = device.current_config_version
        device.config.is_synced = False

    db.commit()

    default_mappings = {"1": 100, "2": 200, "5": 500, "10": 1000}
    return CoinSettingsResponse(
        device_id=device.device_id,
        acceptor_mode=cfg.get("acceptor_mode", "PULSE_TRAIN"),
        pulse_mappings=cfg.get("pulse_mappings", default_mappings),
        debounce_ms=cfg.get("debounce_ms", 50),
        coin_escrow_enabled=cfg.get("coin_escrow_enabled", True),
        change_dispenser_fitted=cfg.get("change_dispenser_fitted", False),
    )


@router.get("/{device_id}/coins/transactions", response_model=List[VendingTransactionResponse])
def get_coin_transactions(
    device: Device = Depends(require_device_module("COIN_PAYMENT")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: COIN_PAYMENT] Retrieve cash/coin collection records and denomination counts.
    """
    txs = db.query(Transaction).filter(
        Transaction.device_id == device.id,
        Transaction.transaction_type == "COIN_VEND",
    ).order_by(Transaction.transacted_at.desc()).limit(50).all()

    return [
        VendingTransactionResponse(
            id=t.id,
            transaction_number=t.transaction_number,
            device_id=device.device_id,
            transaction_type=t.transaction_type,
            amount_in_rupees=t.amount / 100.0,
            coins_inserted=t.coins_inserted,
            change_dispensed=t.change_dispensed,
            dispense_status=t.dispense_status,
            transacted_at=t.transacted_at,
        )
        for t in txs
    ]


# ------------------------------------------------------------------------------
# PRODUCT CATALOG ENDPOINTS
# ------------------------------------------------------------------------------

@router.get("/products", response_model=List[ProductResponse])
def get_products(
    client_id: Optional[str] = Query(None, description="Optional Client UUID filter (manufacturer only)"),
    active_only: bool = Query(False, description="Filter for only active products"),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    List catalog products for client tenant.
    Enforces multi-tenant data boundaries.
    """
    effective_client_id = client_id if context.is_manufacturer and client_id else context.client_id
    products = list_products(
        db=db,
        client_id=effective_client_id,
        is_manufacturer=context.is_manufacturer,
        active_only=active_only,
    )
    return [_format_product(p) for p in products]


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
def create_new_product(
    payload: ProductCreateRequest,
    client_id: Optional[str] = Query(None, description="Client UUID (required if manufacturer superadmin)"),
    request: Request = None,
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Register a new product in the client tenant catalog.
    """
    target_client_id = context.client_id
    if context.is_manufacturer:
        target_client_id = client_id or context.client_id
    if not target_client_id:
        raise ForbiddenException("Client ID must be specified for product creation.")

    client_ip = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    product = create_product(
        db=db,
        client_id=target_client_id,
        payload=payload,
        actor_user_id=context.user.id,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    return _format_product(product)


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_single_product(
    product_id: str = Path(..., description="Product UUID or product_code"),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Retrieve single product detail by ID or SKU.
    """
    product = get_product(
        db=db,
        product_id=product_id,
        client_id=context.client_id,
        is_manufacturer=context.is_manufacturer,
    )
    return _format_product(product)


@router.put("/products/{product_id}", response_model=ProductResponse)
def update_existing_product(
    payload: ProductUpdateRequest,
    product_id: str = Path(..., description="Product UUID or product_code"),
    request: Request = None,
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Update product details.
    PRICE UPDATE ENGINE:
    If product price changes, all assigned vending machines across the fleet
    automatically receive configuration version bumps and live MQTT sync notifications.
    """
    client_ip = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    product, _ = update_product(
        db=db,
        product_id=product_id,
        payload=payload,
        client_id=context.client_id,
        is_manufacturer=context.is_manufacturer,
        actor_user_id=context.user.id,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    return _format_product(product)


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_existing_product(
    product_id: str = Path(..., description="Product UUID or product_code"),
    request: Request = None,
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Delete product from catalog. Fails if active slots reference it.
    """
    client_ip = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    delete_product(
        db=db,
        product_id=product_id,
        client_id=context.client_id,
        is_manufacturer=context.is_manufacturer,
        actor_user_id=context.user.id,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    return None


# ------------------------------------------------------------------------------
# MACHINE SLOT MANAGEMENT ENDPOINTS
# ------------------------------------------------------------------------------

@router.get("/{device_id}/slots", response_model=List[MachineSlotResponse])
def get_device_slots(
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    List all physical dispensing slots on a vending machine.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    slots = list_machine_slots(db=db, device=device)
    return [_format_slot(s, device) for s in slots]


@router.put("/{device_id}/slots/{slot_number}", response_model=MachineSlotResponse)
def configure_single_slot(
    payload: MachineSlotConfigureRequest,
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    slot_number: int = Path(..., ge=1, le=100, description="Slot index (1, 2, 3...)"),
    request: Request = None,
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Configure a single physical slot (product binding, price override, motor pin, capacity, stock).
    Automatically increments device configuration version and pushes MQTT event.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    client_ip = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    slot = configure_slot(
        db=db,
        device=device,
        slot_number=slot_number,
        payload=payload,
        actor_user_id=context.user.id,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    return _format_slot(slot, device)


@router.post("/{device_id}/slots/bulk", response_model=List[MachineSlotResponse])
def configure_multiple_slots(
    payload: MachineSlotBulkConfigureRequest,
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    request: Request = None,
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Bulk configure all slots on a vending machine.
    Generates a single configuration version bump and MQTT notification.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    client_ip = request.client.host if request and request.client else None
    user_agent = request.headers.get("user-agent") if request else None

    slots = bulk_configure_slots(
        db=db,
        device=device,
        slots_items=payload.slots,
        actor_user_id=context.user.id,
        ip_address=client_ip,
        user_agent=user_agent,
    )
    return [_format_slot(s, device) for s in slots]


@router.post("/{device_id}/slots/{slot_number}/restock", response_model=MachineSlotResponse)
def restock_single_slot(
    payload: MachineSlotRestockRequest,
    device_id: str = Path(..., description="Device ID (e.g. VM-000001)"),
    slot_number: int = Path(..., ge=1, le=100, description="Slot index"),
    context: TenantContext = Depends(require_roles("MANUFACTURER_SUPERADMIN", "MANUFACTURER_ADMIN", "CLIENT_ADMIN", "CLIENT_OPERATOR")),
    db: Session = Depends(get_db),
):
    """
    Record stock replenishment for a vending slot without triggering a firmware config version bump.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

    slot = restock_slot(
        db=db,
        device=device,
        slot_number=slot_number,
        quantity_added=payload.quantity_added,
        new_stock_level=payload.new_stock_level,
        actor_user_id=context.user.id,
    )
    return _format_slot(slot, device)

