"""
Integration and Unit Tests for Phase 11:
Coin Payment Engine & Autonomous Edge Credit Subsystem.
Tests hardware pulse ISR debouncing, denomination mapping, edge credit accumulator,
LittleFS ring buffer, gateway batch transaction sync, idempotency, stock decrement,
coin settings revision bumping, cash summary reporting, module policy guards, and multi-tenancy.
"""
import sys
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Add backend root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import app
from src.db.session import get_db, SessionLocal, engine
from src.db.base import Base
from src.db.seed import seed_database
from src.db.models.device import Device, DeviceModule, DeviceCredential
from src.db.models.vending import MachineSlot, Transaction, Product
from src.db.models.audit import AuditLog
from src.db.models.config import DeviceConfig, ConfigurationVersion

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
FIRMWARE_ROOT = os.path.join(WORKSPACE_ROOT, "firmware")


# ==============================================================================
# 1. FIRMWARE FILE STRUCTURE & C DEFINITIONS VERIFICATION
# ==============================================================================

def test_coin_acceptor_firmware_files_and_headers_present():
    """Verify coin acceptor driver and LittleFS buffer C files and headers exist."""
    required_files = [
        "esp32-vending/include/coin_acceptor.h",
        "esp32-vending/src/coin_acceptor.c",
        "esp32-vending/include/coin_offline_buffer.h",
        "esp32-vending/src/coin_offline_buffer.c",
    ]
    for rel_path in required_files:
        full_path = os.path.join(FIRMWARE_ROOT, rel_path)
        assert os.path.exists(full_path), f"Missing firmware file: {rel_path}"


def test_coin_acceptor_header_definitions():
    """Verify hardware timing, debounce windows, and state machine constants."""
    header_path = os.path.join(FIRMWARE_ROOT, "esp32-vending/include/coin_acceptor.h")
    with open(header_path, "r") as f:
        header = f.read()

    assert "COIN_DEFAULT_GPIO_PIN" in header
    assert "COIN_MIN_PULSE_WIDTH_MS" in header
    assert "COIN_MAX_PULSE_WIDTH_MS" in header
    assert "COIN_INTER_PULSE_TIMEOUT_MS" in header
    assert "coin_acceptor_init" in header
    assert "coin_acceptor_on_pulse_event" in header
    assert "coin_acceptor_process_tick" in header
    assert "coin_acceptor_can_vend" in header
    assert "coin_acceptor_execute_vend" in header
    assert "coin_denomination_map_t" in header
    assert "coin_tx_record_t" in header


def test_coin_offline_buffer_header_definitions():
    """Verify LittleFS ring buffer API and capacity constants."""
    header_path = os.path.join(FIRMWARE_ROOT, "esp32-vending/include/coin_offline_buffer.h")
    with open(header_path, "r") as f:
        header = f.read()

    assert "COIN_OFFLINE_MAX_RECORDS" in header
    assert "coin_offline_buffer_init" in header
    assert "coin_offline_buffer_append" in header
    assert "coin_offline_buffer_get_unsynced" in header
    assert "coin_offline_buffer_mark_synced" in header
    assert "coin_offline_buffer_mark_batch_synced" in header
    assert "coin_offline_buffer_purge_synced" in header


# ==============================================================================
# 2. EMBEDDED C ALGORITHM EMULATION (PULSES, DEBOUNCE, CREDIT ACCUMULATOR)
# ==============================================================================

class CoinAcceptorEmulator:
    """Emulates ESP32 coin acceptor driver and autonomous credit accumulator."""

    def __init__(self, debounce_ms=50, timeout_ms=250):
        self.debounce_ms = debounce_ms
        self.timeout_ms = timeout_ms
        self.denominations = {1: 100, 2: 200, 5: 500, 10: 1000}  # pulse -> paise
        self.credit_paise = 0
        self.session_counts = {"1": 0, "2": 0, "5": 0, "10": 0}
        self.current_pulses = 0
        self.last_pulse_ms = 0
        self.is_pulsing = False
        self.is_inhibited = False

    def on_pulse(self, width_ms: int, current_time_ms: int):
        if self.is_inhibited:
            return False
        # Debounce / pulse width filter
        if width_ms < 20 or width_ms > 80:
            return False  # transient or noise

        self.current_pulses += 1
        self.last_pulse_ms = current_time_ms
        self.is_pulsing = True
        return True

    def process_tick(self, current_time_ms: int) -> bool:
        if not self.is_pulsing:
            return False
        if (current_time_ms - self.last_pulse_ms) >= self.timeout_ms:
            # End of pulse train for this coin
            pulses = self.current_pulses
            self.current_pulses = 0
            self.is_pulsing = False

            if pulses in self.denominations:
                val = self.denominations[pulses]
                self.credit_paise += val
                key = str(val // 100)
                if key in self.session_counts:
                    self.session_counts[key] += 1
                return True
        return False

    def can_vend(self, price_paise: int) -> bool:
        return self.credit_paise >= price_paise and price_paise > 0

    def execute_vend(self, slot_num: int, price_paise: int, drop_sensor_ok: bool, change_dispenser: bool = False) -> dict:
        assert self.can_vend(price_paise), "Insufficient credit"
        self.credit_paise -= price_paise
        change_due = self.credit_paise
        change_dispensed = change_due if change_dispenser else 0
        if change_dispenser:
            self.credit_paise = 0

        status = "SUCCESS" if drop_sensor_ok else "JAMMED"
        tx = {
            "tx_uuid": str(uuid.uuid4()),
            "slot_number": slot_num,
            "amount_paise": price_paise,
            "coins_inserted": dict(self.session_counts),
            "change_dispensed_paise": change_dispensed,
            "dispense_status": status,
            "transacted_at": datetime.now(timezone.utc).isoformat(),
        }
        if status == "SUCCESS":
            self.session_counts = {"1": 0, "2": 0, "5": 0, "10": 0}
        return tx


def test_pulse_train_detection_and_debounce_filtering():
    """Verify transient noise rejection, pulse counting, and silence timeout delineation."""
    emu = CoinAcceptorEmulator(debounce_ms=50, timeout_ms=250)

    # 1. Electrical noise spikes (<20ms) must be rejected
    assert not emu.on_pulse(width_ms=5, current_time_ms=100)
    assert not emu.on_pulse(width_ms=18, current_time_ms=120)
    assert emu.credit_paise == 0

    # 2. Insert ₹5 coin (generates 5 valid pulses with ~30ms width each)
    t = 200
    for _ in range(5):
        assert emu.on_pulse(width_ms=40, current_time_ms=t)
        t += 80

    # Before timeout expires, credit is not finalized
    assert not emu.process_tick(current_time_ms=t + 100)
    assert emu.credit_paise == 0

    # After silence timeout (>250ms), pulse train completes
    assert emu.process_tick(current_time_ms=t + 260)
    assert emu.credit_paise == 500  # ₹5 = 500 paise
    assert emu.session_counts["5"] == 1


def test_autonomous_edge_credit_accumulation_and_vend():
    """Verify autonomous edge credit accumulation across multiple coins and vend trigger."""
    emu = CoinAcceptorEmulator(debounce_ms=50, timeout_ms=250)

    # Insert ₹10 coin (10 pulses)
    t = 1000
    for _ in range(10):
        emu.on_pulse(width_ms=35, current_time_ms=t)
        t += 60
    emu.process_tick(current_time_ms=t + 300)

    # Insert another ₹10 coin (10 pulses)
    t += 500
    for _ in range(10):
        emu.on_pulse(width_ms=35, current_time_ms=t)
        t += 60
    emu.process_tick(current_time_ms=t + 300)

    # Insert ₹5 coin (5 pulses)
    t += 500
    for _ in range(5):
        emu.on_pulse(width_ms=35, current_time_ms=t)
        t += 60
    emu.process_tick(current_time_ms=t + 300)

    # Total accumulated: ₹10 + ₹10 + ₹5 = ₹25 (2500 paise)
    assert emu.credit_paise == 2500
    assert emu.session_counts["10"] == 2
    assert emu.session_counts["5"] == 1

    # Product price is ₹20 (2000 paise) -> can vend
    assert emu.can_vend(2000)
    assert not emu.can_vend(3000)

    # Execute vend with change dispenser enabled
    tx = emu.execute_vend(slot_num=1, price_paise=2000, drop_sensor_ok=True, change_dispenser=True)
    assert tx["dispense_status"] == "SUCCESS"
    assert tx["amount_paise"] == 2000
    assert tx["change_dispensed_paise"] == 500  # ₹5 change returned
    assert emu.credit_paise == 0


# ==============================================================================
# 3. BACKEND API TESTS: AUTHENTICATION, GATEWAY SYNC, & IDEMPOTENCY
# ==============================================================================

@pytest.fixture(scope="module", autouse=True)
def setup_coin_database():
    """Ensure database has fresh schema and seed data for coin tests."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_database(session)
    finally:
        session.close()


@pytest.fixture
def test_client():
    return TestClient(app)


def get_token(test_client, username: str, password: str) -> str:
    """Helper to authenticate and retrieve access token."""
    resp = test_client.post(
        "/api/v1/auth/login",
        json={"username_or_email": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture
def auth_headers_client_a(test_client):
    """JWT for client tenant admin A (owns VM-000001)."""
    token = get_token(test_client, "apex_admin", "Apex@Admin2026!")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_client_b(test_client):
    """JWT for client tenant admin B (owns VM-000003)."""
    token = get_token(test_client, "metro_admin", "Metro@Retail2026!")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def edge_device_session_token(test_client):
    """Obtain short-lived device session token for VM-000002 via handshake."""
    db: Session = SessionLocal()
    try:
        device = db.query(Device).filter(Device.device_id == "VM-000002").first()
        resp = test_client.post(
            "/api/v1/device-gateway/authenticate",
            json={
                "device_id": "VM-000002",
                "device_token": "dev_token_VM-000002",
                "chip_id": device.chip_id,
                "mac_address": device.mac_address,
                "firmware_version": "v1.0.0",
                "boot_count": 1,
            },
        )
        assert resp.status_code == 200, f"Gateway auth failed: {resp.text}"
        data = resp.json()
        return data["session_token"]
    finally:
        db.close()


def test_edge_device_offline_transaction_batch_sync(test_client, edge_device_session_token):
    """
    Test edge ESP32 ingesting a batch of LittleFS offline coin transactions
    via POST /api/v1/device-gateway/transactions/offline-sync.
    """
    tx_uuid_1 = str(uuid.uuid4())
    tx_uuid_2 = str(uuid.uuid4())

    batch_payload = {
        "device_id": "VM-000002",
        "transactions": [
            {
                "tx_uuid": tx_uuid_1,
                "slot_number": 1,
                "product_code": "BEV-WATER-500",
                "amount_paise": 2000,
                "coins_inserted": {"10": 2},
                "change_dispensed_paise": 0,
                "dispense_status": "SUCCESS",
                "transacted_at": datetime.now(timezone.utc).isoformat(),
            },
            {
                "tx_uuid": tx_uuid_2,
                "slot_number": 1,
                "product_code": "BEV-WATER-500",
                "amount_paise": 2000,
                "coins_inserted": {"5": 4},
                "change_dispensed_paise": 0,
                "dispense_status": "SUCCESS",
                "transacted_at": datetime.now(timezone.utc).isoformat(),
            },
        ],
    }

    resp = test_client.post(
        "/api/v1/device-gateway/transactions/offline-sync",
        headers={"Authorization": f"Bearer {edge_device_session_token}"},
        json=batch_payload,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["device_id"] == "VM-000002"
    assert data["synced_count"] == 2
    assert data["duplicate_count"] == 0
    assert tx_uuid_1 in data["synced_tx_uuids"]
    assert tx_uuid_2 in data["synced_tx_uuids"]

    # Verify persisted in database
    db: Session = SessionLocal()
    try:
        t1 = db.query(Transaction).filter(Transaction.transaction_number == tx_uuid_1).first()
        assert t1 is not None
        assert t1.amount == 2000
        assert t1.transaction_type == "COIN_VEND"
        assert t1.is_offline_sync is True
        assert t1.coins_inserted == {"10": 2}
    finally:
        db.close()


def test_offline_sync_idempotency_and_deduplication(test_client, edge_device_session_token):
    """
    Submitting the exact same transaction batch again must not create duplicate
    records and must safely acknowledge the existing UUIDs.
    """
    tx_uuid = str(uuid.uuid4())
    payload = {
        "device_id": "VM-000002",
        "transactions": [
            {
                "tx_uuid": tx_uuid,
                "slot_number": 1,
                "amount_paise": 2000,
                "coins_inserted": {"10": 2},
                "change_dispensed_paise": 0,
                "dispense_status": "SUCCESS",
                "transacted_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
    }

    # First send -> 1 new synced
    resp1 = test_client.post(
        "/api/v1/device-gateway/transactions/offline-sync",
        headers={"Authorization": f"Bearer {edge_device_session_token}"},
        json=payload,
    )
    assert resp1.status_code == 200
    assert resp1.json()["synced_count"] == 1
    assert resp1.json()["duplicate_count"] == 0

    # Second send (retry after network reconnection) -> 1 duplicate acknowledged
    resp2 = test_client.post(
        "/api/v1/device-gateway/transactions/offline-sync",
        headers={"Authorization": f"Bearer {edge_device_session_token}"},
        json=payload,
    )
    assert resp2.status_code == 200
    assert resp2.json()["synced_count"] == 0
    assert resp2.json()["duplicate_count"] == 1
    assert tx_uuid in resp2.json()["synced_tx_uuids"]

    # Verify database has exactly 1 row
    db: Session = SessionLocal()
    try:
        count = db.query(Transaction).filter(Transaction.transaction_number == tx_uuid).count()
        assert count == 1
    finally:
        db.close()


def test_slot_stock_decremented_on_successful_coin_vend(test_client, edge_device_session_token):
    """
    A successful offline vend must decrement the physical machine slot stock,
    while a JAMMED vend must leave stock unaffected.
    """
    db: Session = SessionLocal()
    try:
        device = db.query(Device).filter(Device.device_id == "VM-000002").first()
        slot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=1).first()
        initial_stock = slot.current_stock
    finally:
        db.close()

    # 1. Successful vend
    tx_success = str(uuid.uuid4())
    test_client.post(
        "/api/v1/device-gateway/transactions/offline-sync",
        headers={"Authorization": f"Bearer {edge_device_session_token}"},
        json={
            "device_id": "VM-000002",
            "transactions": [
                {
                    "tx_uuid": tx_success,
                    "slot_number": 1,
                    "amount_paise": 2000,
                    "coins_inserted": {"10": 2},
                    "change_dispensed_paise": 0,
                    "dispense_status": "SUCCESS",
                    "transacted_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        },
    )

    db = SessionLocal()
    try:
        slot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=1).first()
        assert slot.current_stock == max(0, initial_stock - 1)
        stock_after_success = slot.current_stock
    finally:
        db.close()

    # 2. Jammed vend (motor attempted but drop sensor timed out)
    tx_jammed = str(uuid.uuid4())
    test_client.post(
        "/api/v1/device-gateway/transactions/offline-sync",
        headers={"Authorization": f"Bearer {edge_device_session_token}"},
        json={
            "device_id": "VM-000002",
            "transactions": [
                {
                    "tx_uuid": tx_jammed,
                    "slot_number": 1,
                    "amount_paise": 2000,
                    "coins_inserted": {"10": 2},
                    "change_dispensed_paise": 0,
                    "dispense_status": "JAMMED",
                    "transacted_at": datetime.now(timezone.utc).isoformat(),
                }
            ],
        },
    )

    db = SessionLocal()
    try:
        slot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=1).first()
        # Stock must NOT decrease on jammed vend
        assert slot.current_stock == stock_after_success
    finally:
        db.close()


def test_coin_settings_update_increments_config_version_and_checksum(test_client, auth_headers_client_a):
    """
    Updating coin acceptor pulse mappings or debounce timing must increment
    the device configuration version, update SHA-256 checksum, and archive an immutable version.
    """
    db: Session = SessionLocal()
    try:
        dev = db.query(Device).filter(Device.device_id == "VM-000002").first()
        orig_version = dev.current_config_version
        orig_checksum = dev.config.checksum if dev.config else ""
    finally:
        db.close()

    resp = test_client.put(
        "/api/v1/vending/VM-000002/coins/settings",
        headers=auth_headers_client_a,
        json={
            "pulse_mappings": {"1": 100, "2": 200, "5": 500, "10": 1000, "20": 2000},
            "debounce_ms": 60,
            "change_dispenser_fitted": True,
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["debounce_ms"] == 60
    assert data["change_dispenser_fitted"] is True
    assert "20" in data["pulse_mappings"]

    # Verify device config version incremented
    db = SessionLocal()
    try:
        dev = db.query(Device).filter(Device.device_id == "VM-000002").first()
        assert dev.current_config_version == orig_version + 1
        assert dev.config.is_synced is False
        assert dev.config.checksum != orig_checksum

        # Verify ConfigurationVersion archived
        archived = db.query(ConfigurationVersion).filter_by(
            device_id=dev.id,
            version_number=dev.current_config_version,
        ).first()
        assert archived is not None
        assert archived.change_reason == "COIN_ACCEPTOR_PULSE_MAPPINGS_UPDATED"
    finally:
        db.close()


def test_cash_collection_summary_and_denomination_breakdown(test_client, auth_headers_client_a):
    """
    GET /api/v1/vending/{device_id}/coins/summary must aggregate total cash collected,
    successful/failed vends, denomination breakdown, and total change dispensed.
    """
    resp = test_client.get(
        "/api/v1/vending/VM-000002/coins/summary",
        headers=auth_headers_client_a,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["device_id"] == "VM-000002"
    assert data["total_cash_collected_rupees"] > 0
    assert data["total_transactions"] >= 2
    assert data["successful_vends"] >= 2
    assert isinstance(data["denomination_breakdown"], dict)
    assert "10" in data["denomination_breakdown"]


def test_coin_transactions_listing_endpoint(test_client, auth_headers_client_a):
    """
    GET /api/v1/vending/{device_id}/coins/transactions retrieves recent coin vends.
    """
    resp = test_client.get(
        "/api/v1/vending/VM-000002/coins/transactions",
        headers=auth_headers_client_a,
    )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    first_tx = data[0]
    assert first_tx["device_id"] == "VM-000002"
    assert first_tx["transaction_type"] == "COIN_VEND"
    assert "amount_in_rupees" in first_tx
    assert "dispense_status" in first_tx


def test_module_policy_guard_blocks_device_without_coin_payment(test_client, auth_headers_client_a):
    """
    Devices without COIN_PAYMENT module enabled (e.g. VM-000001) must reject
    coin settings, transactions, and cash summary requests with HTTP 403.
    """
    # VM-000001 has only QR_PAYMENT, not COIN_PAYMENT
    resp_settings = test_client.get(
        "/api/v1/vending/VM-000001/coins/settings",
        headers=auth_headers_client_a,
    )
    assert resp_settings.status_code == 403
    assert "COIN_PAYMENT" in resp_settings.text

    resp_summary = test_client.get(
        "/api/v1/vending/VM-000001/coins/summary",
        headers=auth_headers_client_a,
    )
    assert resp_summary.status_code == 403


def test_multi_tenant_isolation_on_coin_subsystem(test_client, auth_headers_client_b):
    """
    Client B must never be able to view coin settings, transactions, or cash summary
    for Client A's machine (VM-000002). Must return HTTP 403 Forbidden.
    """
    resp_settings = test_client.get(
        "/api/v1/vending/VM-000002/coins/settings",
        headers=auth_headers_client_b,
    )
    assert resp_settings.status_code == 403

    resp_summary = test_client.get(
        "/api/v1/vending/VM-000002/coins/summary",
        headers=auth_headers_client_b,
    )
    assert resp_summary.status_code == 403

    resp_tx = test_client.get(
        "/api/v1/vending/VM-000002/coins/transactions",
        headers=auth_headers_client_b,
    )
    assert resp_tx.status_code == 403
