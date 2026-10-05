"""
Vending Machine Subsystem API endpoints.
Enforces strict dynamic module policy guards on QR and Coin configurations and transactions.
"""
from typing import List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.device import Device, DeviceModule
from src.db.models.vending import Transaction
from src.core.security.dependencies import (
    TenantContext,
    get_tenant_context,
    require_device_module,
)
from src.api.v1.vending.schemas import (
    QRSettingsResponse,
    QRSettingsUpdateRequest,
    CoinSettingsResponse,
    CoinSettingsUpdateRequest,
    VendingTransactionResponse,
    ClientFleetCapabilityItem,
)

router = APIRouter(prefix="/vending", tags=["Vending Subsystem"])


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
