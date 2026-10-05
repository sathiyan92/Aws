"""
Coin Service for Vending Machines.
Manages electronic coin acceptor configurations, autonomous edge offline transaction ingestion,
cash collection reconciliation, and multi-tenant financial reporting.
"""
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from src.db.base import utc_now
from src.db.models.device import Device, DeviceModule
from src.db.models.vending import MachineSlot, Transaction, Product
from src.db.models.audit import AuditLog
from src.core.exceptions.errors import (
    ForbiddenException,
    NotFoundException,
    ConflictException,
)
from src.services.config_service import (
    build_device_composite_payload,
    sync_device_config_record,
)
from src.api.v1.vending.schemas import (
    CoinSettingsResponse,
    CoinSettingsUpdateRequest,
    CoinOfflineSyncRequest,
    CoinOfflineSyncResponse,
    CoinCashSummaryResponse,
)


def get_device_coin_settings(db: Session, device: Device) -> CoinSettingsResponse:
    """
    Retrieve electronic coin acceptor settings for a vending machine.
    Enforces COIN_PAYMENT module guard.
    """
    coin_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="COIN_PAYMENT").first()
    if not coin_mod or not coin_mod.is_enabled:
        raise ForbiddenException(
            f"Module 'COIN_PAYMENT' is disabled for device '{device.device_id}'. Cannot access coin settings."
        )

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


def update_device_coin_settings(
    db: Session,
    device: Device,
    payload: CoinSettingsUpdateRequest,
    actor_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> CoinSettingsResponse:
    """
    Update coin pulse-to-value mappings and debounce parameters.
    Automatically rebuilds composite device configuration, increments
    config version, recalculates SHA-256 checksum, archives version,
    and publishes MQTT notification to the edge device.
    """
    coin_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="COIN_PAYMENT").first()
    if not coin_mod or not coin_mod.is_enabled:
        raise ForbiddenException(
            f"Module 'COIN_PAYMENT' is disabled for device '{device.device_id}'."
        )

    cfg = dict(coin_mod.configuration or {})

    if payload.pulse_mappings is not None:
        cfg["pulse_mappings"] = payload.pulse_mappings
    if payload.debounce_ms is not None:
        cfg["debounce_ms"] = payload.debounce_ms
    if payload.change_dispenser_fitted is not None:
        cfg["change_dispenser_fitted"] = payload.change_dispenser_fitted

    coin_mod.configuration = cfg
    db.flush()

    # Rebuild composite configuration payload including updated coin settings
    composite_payload = build_device_composite_payload(device)

    # Sync and archive new configuration version
    sync_device_config_record(
        db=db,
        device=device,
        raw_payload=composite_payload,
        change_reason="COIN_ACCEPTOR_PULSE_MAPPINGS_UPDATED",
        actor_user_id=actor_user_id,
        ip_address=ip_address,
    )

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


def process_offline_transaction_batch(
    db: Session,
    device: Device,
    payload: CoinOfflineSyncRequest,
) -> CoinOfflineSyncResponse:
    """
    Ingests a batch of un-synced offline coin transactions from an authenticated ESP32.
    Validates records, enforces idempotency, updates inventory stock counters,
    and creates financial transaction ledger entries.
    """
    # 1. Validate device identity and module capability
    if device.device_id != payload.device_id:
        raise ForbiddenException(
            f"Device ID mismatch in sync payload: authenticated as '{device.device_id}' but payload specifies '{payload.device_id}'."
        )

    coin_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="COIN_PAYMENT").first()
    if not coin_mod or not coin_mod.is_enabled:
        raise ForbiddenException(
            f"Module 'COIN_PAYMENT' is disabled for device '{device.device_id}'. Offline coin sync rejected."
        )

    synced_tx_uuids: List[str] = []
    rejected_tx_uuids: List[str] = []
    duplicate_count = 0
    new_synced_count = 0

    # Cache machine slots for fast lookup
    slots_by_num: Dict[int, MachineSlot] = {
        s.slot_number: s for s in device.slots
    }

    for item in payload.transactions:
        # Idempotency check: see if transaction already persisted
        existing_tx = db.query(Transaction).filter(
            Transaction.device_id == device.id,
            Transaction.transaction_number == item.tx_uuid,
        ).first()

        if existing_tx:
            # Already persisted; acknowledge so edge can clear from ring buffer
            synced_tx_uuids.append(item.tx_uuid)
            duplicate_count += 1
            continue

        try:
            # Normalize dispense status
            dispense_status = item.dispense_status.upper().strip()
            if dispense_status not in ["SUCCESS", "FAILURE", "JAMMED"]:
                dispense_status = "SUCCESS"

            # Create immutable financial transaction
            tx = Transaction(
                transaction_number=item.tx_uuid,
                client_id=device.client_id,
                device_id=device.id,
                transaction_type="COIN_VEND",
                amount=item.amount_paise,
                currency="INR",
                coins_inserted=item.coins_inserted,
                change_dispensed=item.change_dispensed_paise,
                dispense_status=dispense_status,
                is_offline_sync=True,
                transacted_at=item.transacted_at,
            )
            db.add(tx)
            db.flush()

            # If dispense was successful, decrement machine slot stock
            if dispense_status == "SUCCESS":
                slot = slots_by_num.get(item.slot_number)
                if slot:
                    old_stock = slot.current_stock
                    slot.current_stock = max(0, slot.current_stock - 1)
                    db.add(AuditLog(
                        client_id=device.client_id,
                        user_id=None,
                        action="SLOT_INVENTORY_DISPENSED",
                        entity_type="SLOT",
                        entity_id=slot.id,
                        old_state={"current_stock": old_stock},
                        new_state={"current_stock": slot.current_stock, "tx_uuid": item.tx_uuid},
                    ))

            synced_tx_uuids.append(item.tx_uuid)
            new_synced_count += 1

        except Exception as ex:
            rejected_tx_uuids.append(item.tx_uuid)

    # Record overall sync audit log
    if new_synced_count > 0 or duplicate_count > 0:
        db.add(AuditLog(
            client_id=device.client_id,
            user_id=None,
            action="COIN_TRANSACTIONS_SYNCED",
            entity_type="DEVICE",
            entity_id=device.id,
            old_state=None,
            new_state={
                "device_id": device.device_id,
                "new_synced_count": new_synced_count,
                "duplicate_count": duplicate_count,
            },
        ))

    db.commit()

    return CoinOfflineSyncResponse(
        device_id=device.device_id,
        synced_count=new_synced_count,
        duplicate_count=duplicate_count,
        synced_tx_uuids=synced_tx_uuids,
        rejected_tx_uuids=rejected_tx_uuids,
        message=f"Synced {new_synced_count} new transactions, {duplicate_count} duplicates acknowledged.",
    )


def get_device_cash_summary(db: Session, device: Device) -> CoinCashSummaryResponse:
    """
    Compute aggregate cash collection summary and coin denomination breakdown
    for a given vending machine.
    """
    coin_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="COIN_PAYMENT").first()
    if not coin_mod or not coin_mod.is_enabled:
        raise ForbiddenException(
            f"Module 'COIN_PAYMENT' is disabled for device '{device.device_id}'."
        )

    transactions = db.query(Transaction).filter(
        Transaction.device_id == device.id,
        Transaction.transaction_type == "COIN_VEND",
    ).order_by(Transaction.transacted_at.desc()).all()

    total_amount_paise = 0
    total_change_paise = 0
    successful_vends = 0
    failed_vends = 0
    denomination_counts: Dict[str, int] = {"1": 0, "2": 0, "5": 0, "10": 0}
    last_sync_at = None

    for tx in transactions:
        if tx.dispense_status == "SUCCESS":
            total_amount_paise += tx.amount
            successful_vends += 1
        else:
            failed_vends += 1

        total_change_paise += tx.change_dispensed

        if tx.created_at and (last_sync_at is None or tx.created_at > last_sync_at):
            last_sync_at = tx.created_at

        # Aggregate denomination breakdown
        if tx.coins_inserted and isinstance(tx.coins_inserted, dict):
            for denom, count in tx.coins_inserted.items():
                denom_key = str(denom)
                denomination_counts[denom_key] = denomination_counts.get(denom_key, 0) + int(count)

    return CoinCashSummaryResponse(
        device_id=device.device_id,
        total_cash_collected_rupees=round(total_amount_paise / 100.0, 2),
        total_transactions=len(transactions),
        successful_vends=successful_vends,
        failed_vends=failed_vends,
        denomination_breakdown=denomination_counts,
        total_change_dispensed_rupees=round(total_change_paise / 100.0, 2),
        last_sync_at=last_sync_at,
    )
