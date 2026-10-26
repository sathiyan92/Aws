"""
Integration and Unit Tests for Phase 12:
Dynamic QR Payment Engine & Ephemeral Purchase Intent Lifecycle.
Tests dynamic price resolution, ephemeral UPI QR payloads, countdown timers,
out-of-stock guards, module policy enforcement, order cancellation, polling,
expiration transitions, multi-tenancy, and audit logging.
"""
import sys
import os
import re
import uuid
import urllib.parse
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Add backend root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import app
from src.db.session import SessionLocal, engine
from src.db.base import Base, utc_now
from src.db.seed import seed_database
from src.db.models.device import Device, DeviceModule
from src.db.models.vending import MachineSlot, Product, Order, Payment
from src.db.models.audit import AuditLog

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
FIRMWARE_ROOT = os.path.join(WORKSPACE_ROOT, "firmware")


# ==============================================================================
# 1. FIRMWARE FILE STRUCTURE & C DEFINITIONS VERIFICATION
# ==============================================================================

def test_firmware_qr_payment_files_and_headers():
    """Verify QR payment C header and driver files exist and define timing constants."""
    header_path = os.path.join(FIRMWARE_ROOT, "esp32-vending/include/qr_payment.h")
    source_path = os.path.join(FIRMWARE_ROOT, "esp32-vending/src/qr_payment.c")

    assert os.path.exists(header_path), f"Missing {header_path}"
    assert os.path.exists(source_path), f"Missing {source_path}"

    with open(header_path, "r") as f:
        header = f.read()

    assert "QR_DEFAULT_TIMEOUT_SEC" in header
    assert "qr_payment_init" in header
    assert "qr_payment_start_session" in header
    assert "qr_payment_process_tick" in header
    assert "qr_payment_cancel_session" in header
    assert "qr_payment_is_active" in header
    assert "qr_payment_get_seconds_remaining" in header
    assert "qr_payment_set_authorized" in header
    assert "qr_payment_render_ascii_preview" in header


class QRPaymentEmulator:
    """Emulates ESP32 dynamic QR countdown timer and state transitions."""

    def __init__(self, timeout_sec: int = 180):
        self.state = "IDLE"
        self.timeout_sec = timeout_sec
        self.seconds_remaining = 0
        self.order_id = ""
        self.order_number = ""
        self.amount_paise = 0
        self.upi_uri = ""
        self.accumulated_ms = 0

    def start_session(self, order_id: str, order_number: str, amount_paise: int, upi_uri: str):
        self.order_id = order_id
        self.order_number = order_number
        self.amount_paise = amount_paise
        self.upi_uri = upi_uri
        self.seconds_remaining = self.timeout_sec
        self.state = "DISPLAYING"
        self.accumulated_ms = 0

    def process_tick(self, delta_ms: int):
        if self.state != "DISPLAYING":
            return
        self.accumulated_ms += delta_ms
        while self.accumulated_ms >= 1000:
            self.accumulated_ms -= 1000
            self.seconds_remaining -= 1
            if self.seconds_remaining <= 0:
                self.seconds_remaining = 0
                self.state = "EXPIRED"
                break

    def cancel(self, reason: str = "CANCELLED"):
        if self.state == "DISPLAYING":
            self.state = "CANCELLED"

    def set_authorized(self):
        if self.state == "DISPLAYING":
            self.state = "AUTHORIZED"


def test_firmware_qr_state_machine_and_countdown_emulation():
    """Verify QR countdown timer, second-by-second decrements, and expiration."""
    emu = QRPaymentEmulator(timeout_sec=5)
    emu.start_session("test-uuid", "ORD-2026-001", 2000, "upi://pay?pa=test@icici&am=20.00")

    assert emu.state == "DISPLAYING"
    assert emu.seconds_remaining == 5

    # Tick 2000ms -> remaining = 3
    emu.process_tick(2000)
    assert emu.seconds_remaining == 3
    assert emu.state == "DISPLAYING"

    # Tick 3000ms -> remaining = 0, state becomes EXPIRED
    emu.process_tick(3000)
    assert emu.seconds_remaining == 0
    assert emu.state == "EXPIRED"


# ==============================================================================
# 2. BACKEND API TESTS: ORDER INITIATION, DYNAMIC PRICING, & LIFECYCLE
# ==============================================================================

@pytest.fixture(scope="module", autouse=True)
def setup_orders_database():
    """Ensure clean database with seed data for order testing."""
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
    resp = test_client.post(
        "/api/v1/auth/login",
        json={"username_or_email": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture
def auth_headers_apex(test_client):
    """JWT for client tenant admin A (Apex Vending Solutions)."""
    token = get_token(test_client, "apex_admin", "Apex@Admin2026!")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth_headers_metro(test_client):
    """JWT for client tenant admin B (Metro Retail Networks)."""
    token = get_token(test_client, "metro_admin", "Metro@Retail2026!")
    return {"Authorization": f"Bearer {token}"}


def test_initiate_order_dynamic_price_resolution(test_client):
    """
    Initiating an order for VM-000001 slot 1 (Water, base price ₹20 = 2000 paise).
    Asserts correct dynamic price resolution, ephemeral UPI QR payload, and 180s countdown.
    """
    resp = test_client.post(
        "/api/v1/orders/initiate",
        json={
            "device_id": "VM-000001",
            "slot_number": 1,
            "customer_phone": "+919876543210",
        },
    )

    assert resp.status_code == 201, f"Order initiation failed: {resp.text}"
    data = resp.json()

    assert data["device_id"] == "VM-000001"
    assert data["slot_number"] == 1
    assert data["product_code"] == "BEV-WATER-500"
    assert data["amount_paise"] == 2000
    assert data["amount_rupees"] == 20.0
    assert data["order_status"] == "PENDING"
    assert data["payment_status"] == "INITIATED"
    assert data["timeout_seconds"] == 180
    assert "ORD-" in data["order_number"]

    # Verify UPI deep-link format
    upi = data["qr_payload"]
    assert upi.startswith("upi://pay?")
    assert "am=20.00" in upi
    assert "cu=INR" in upi
    assert f"tn={data['order_number']}" in upi

    # Verify ASCII preview rendered
    assert data["qr_ascii_preview"] is not None
    assert "SCAN WITH ANY UPI APP" in data["qr_ascii_preview"]


def test_initiate_order_resolves_slot_price_override(test_client):
    """
    When a slot has an override_price set (e.g. ₹28 = 2800 paise instead of ₹20),
    the generated order MUST use the slot override price.
    """
    db: Session = SessionLocal()
    try:
        dev = db.query(Device).filter(Device.device_id == "VM-000001").first()
        slot = db.query(MachineSlot).filter_by(device_id=dev.id, slot_number=1).first()
        slot.override_price = 2800  # ₹28.00 override
        db.commit()
    finally:
        db.close()

    resp = test_client.post(
        "/api/v1/orders/initiate",
        json={"device_id": "VM-000001", "slot_number": 1},
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["amount_paise"] == 2800
    assert data["amount_rupees"] == 28.0
    assert "am=28.00" in data["qr_payload"]

    # Reset override price
    db = SessionLocal()
    try:
        slot = db.query(MachineSlot).filter_by(device_id=dev.id, slot_number=1).first()
        slot.override_price = None
        db.commit()
    finally:
        db.close()


def test_initiate_order_out_of_stock_rejected(test_client):
    """
    If a slot has current_stock == 0, order initiation must be rejected
    with HTTP 409 and error_code='OUT_OF_STOCK'.
    """
    db: Session = SessionLocal()
    try:
        dev = db.query(Device).filter(Device.device_id == "VM-000001").first()
        slot = db.query(MachineSlot).filter_by(device_id=dev.id, slot_number=2).first()
        orig_stock = slot.current_stock
        slot.current_stock = 0  # Mark out of stock
        db.commit()
    finally:
        db.close()

    resp = test_client.post(
        "/api/v1/orders/initiate",
        json={"device_id": "VM-000001", "slot_number": 2},
    )

    assert resp.status_code == 409
    assert "OUT_OF_STOCK" in resp.text

    # Restore stock
    db = SessionLocal()
    try:
        slot = db.query(MachineSlot).filter_by(device_id=dev.id, slot_number=2).first()
        slot.current_stock = orig_stock
        db.commit()
    finally:
        db.close()


def test_initiate_order_disabled_qr_module_rejected(test_client):
    """
    VM-000002 has only COIN_PAYMENT enabled (QR_PAYMENT is disabled).
    Attempting to initiate a dynamic QR order must be rejected with HTTP 403 MODULE_DISABLED_FOR_DEVICE.
    """
    resp = test_client.post(
        "/api/v1/orders/initiate",
        json={"device_id": "VM-000002", "slot_number": 1},
    )

    assert resp.status_code == 403
    assert "MODULE_DISABLED_FOR_DEVICE" in resp.text
    assert "QR_PAYMENT" in resp.text


def test_order_status_polling_and_countdown(test_client):
    """
    GET /api/v1/orders/{order_id} retrieves real-time order status,
    active payment state, and remaining expiration seconds.
    """
    # Create order
    create_resp = test_client.post(
        "/api/v1/orders/initiate",
        json={"device_id": "VM-000001", "slot_number": 1},
    )
    assert create_resp.status_code == 201
    order_id = create_resp.json()["order_id"]

    # Poll status
    poll_resp = test_client.get(f"/api/v1/orders/{order_id}")
    assert poll_resp.status_code == 200
    data = poll_resp.json()

    assert data["order_id"] == order_id
    assert data["order_status"] == "PENDING"
    assert data["payment_status"] == "INITIATED"
    assert data["seconds_remaining"] > 0
    assert data["seconds_remaining"] <= 180
    assert data["qr_payload"] is not None


def test_order_dynamic_expiration_after_timeout(test_client):
    """
    When an order's countdown reaches 0 (expires_at is in the past),
    querying the order detail must automatically transition order_status to EXPIRED
    and payment_status to FAILED.
    """
    # Create order
    create_resp = test_client.post(
        "/api/v1/orders/initiate",
        json={"device_id": "VM-000001", "slot_number": 1},
    )
    order_id = create_resp.json()["order_id"]

    # Artificially expire the order in the database
    db: Session = SessionLocal()
    try:
        order = db.query(Order).filter(Order.id == order_id).first()
        order.expires_at = utc_now() - timedelta(seconds=10)
        db.commit()
    finally:
        db.close()

    # Query order status
    poll_resp = test_client.get(f"/api/v1/orders/{order_id}")
    assert poll_resp.status_code == 200
    data = poll_resp.json()

    assert data["order_status"] == "EXPIRED"
    assert data["payment_status"] == "FAILED"
    assert data["seconds_remaining"] == 0


def test_order_cancellation_by_user(test_client):
    """
    POST /api/v1/orders/{order_id}/cancel successfully cancels a pending order.
    """
    # Create order
    create_resp = test_client.post(
        "/api/v1/orders/initiate",
        json={"device_id": "VM-000001", "slot_number": 1},
    )
    order_id = create_resp.json()["order_id"]

    # Cancel order
    cancel_resp = test_client.post(
        f"/api/v1/orders/{order_id}/cancel?reason=CUSTOMER_CHANGED_MIND"
    )
    assert cancel_resp.status_code == 200
    data = cancel_resp.json()
    assert data["order_status"] == "CANCELLED"

    # Verify detail reflects cancellation
    poll_resp = test_client.get(f"/api/v1/orders/{order_id}")
    assert poll_resp.json()["order_status"] == "CANCELLED"


def test_order_list_multi_tenant_isolation(test_client, auth_headers_apex, auth_headers_metro):
    """
    Apex Admin listing orders only sees Apex's fleet orders.
    Metro Admin does not see Apex's orders.
    """
    # List orders as Apex Admin
    resp_apex = test_client.get("/api/v1/orders", headers=auth_headers_apex)
    assert resp_apex.status_code == 200
    apex_orders = resp_apex.json()
    assert len(apex_orders) >= 1
    # All returned orders must belong to Apex's devices
    for o in apex_orders:
        assert o["device_id"] in ["VM-000001", "VM-000002", "VM-000003"]

    # List orders as Metro Admin (no orders initiated on VM-000004 yet)
    resp_metro = test_client.get("/api/v1/orders", headers=auth_headers_metro)
    assert resp_metro.status_code == 200
    metro_orders = resp_metro.json()
    for o in metro_orders:
        assert o["device_id"] not in ["VM-000001", "VM-000002"]


def test_order_audit_trail_logging(test_client):
    """
    Assert that ORDER_INITIATED and ORDER_CANCELLED create persistent audit log records.
    """
    create_resp = test_client.post(
        "/api/v1/orders/initiate",
        json={"device_id": "VM-000001", "slot_number": 1},
    )
    order_id = create_resp.json()["order_id"]

    test_client.post(f"/api/v1/orders/{order_id}/cancel")

    db: Session = SessionLocal()
    try:
        init_log = db.query(AuditLog).filter_by(
            entity_id=order_id,
            action="ORDER_INITIATED",
        ).first()
        assert init_log is not None
        assert init_log.new_state["slot_number"] == 1

        cancel_log = db.query(AuditLog).filter_by(
            entity_id=order_id,
            action="ORDER_CANCELLED",
        ).first()
        assert cancel_log is not None
        assert cancel_log.new_state["order_status"] == "CANCELLED"
    finally:
        db.close()


def test_razorpay_webhook_and_pending_dispense_flow(test_client):
    """
    Test zero-button price-match vending flow:
    1. Razorpay webhook sends payment.captured for VM-000001 with price matching Slot 1 (1000 paise).
    2. Backend creates an authorized order.
    3. ESP32 polls /orders/pending-dispense/VM-000001 and receives dispense_pending=True.
    4. ESP32 confirms dispense via /orders/{order_id}/dispensed.
    5. Next poll returns dispense_pending=False.
    """
    webhook_payload = {
        "event": "payment.captured",
        "payload": {
            "payment": {
                "entity": {
                    "id": "pay_test_razorpay_9988",
                    "amount": 1000,
                    "currency": "INR",
                    "status": "captured",
                    "notes": {
                        "device_id": "VM-000001"
                    }
                }
            }
        }
    }

    # 1. Razorpay webhook fires
    webhook_resp = test_client.post("/api/v1/orders/razorpay-webhook", json=webhook_payload)
    assert webhook_resp.status_code == 200
    webhook_data = webhook_resp.json()
    assert webhook_data["status"] == "DISPENSE_AUTHORIZED"
    assert webhook_data["slot_number"] == 1
    assert webhook_data["amount_rupees"] == 10.0
    order_id = webhook_data["order_id"]

    # 2. ESP32 checks pending dispense
    poll_resp = test_client.get("/api/v1/orders/pending-dispense/VM-000001")
    assert poll_resp.status_code == 200
    poll_data = poll_resp.json()
    assert poll_data["dispense_pending"] is True
    assert poll_data["slot_number"] == 1
    assert poll_data["order_id"] == order_id

    # 3. ESP32 dispenses and marks complete
    dispense_resp = test_client.post(f"/api/v1/orders/{order_id}/dispensed")
    assert dispense_resp.status_code == 200
    assert dispense_resp.json()["order_status"] == "DISPENSED"

    # 4. Subsequent poll has no pending orders
    second_poll = test_client.get("/api/v1/orders/pending-dispense/VM-000001")
    assert second_poll.status_code == 200
    assert second_poll.json()["dispense_pending"] is False


def test_remote_qr_config_update_by_vendor_or_manufacturer(test_client):
    """
    Test that when Vendor or Manufacturer updates QR code, VPA, or price online:
    1. Initial config returns standard default VPA and price.
    2. Vendor updates to custom Razorpay VPA and new price.
    3. Version increments and new config is immediately returned.
    """
    # 1. Fetch initial QR config
    initial_resp = test_client.get("/api/v1/orders/qr-config/VM-000001")
    assert initial_resp.status_code == 200
    init_data = initial_resp.json()
    init_version = init_data["config_version"]

    # 2. Vendor updates QR VPA, price, and product name online
    update_payload = {
        "razorpay_upi_vpa": "vendor.premium@icici",
        "amount_rupees": 15.00,
        "product_name": "Premium Cold Coffee",
    }
    update_resp = test_client.put("/api/v1/orders/qr-config/VM-000001", json=update_payload)
    assert update_resp.status_code == 200
    updated_data = update_resp.json()
    assert updated_data["razorpay_upi_vpa"] == "vendor.premium@icici"
    assert updated_data["amount_rupees"] == 15.00
    assert updated_data["product_name"] == "Premium Cold Coffee"
    assert "vendor.premium@icici" in updated_data["qr_payload"]
    assert updated_data["config_version"] > init_version


