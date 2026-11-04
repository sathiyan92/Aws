"""
Test Suite for 1,000-User RFID Vending Subsystem.
Verifies:
1. 1,000-card scale creation and lookup
2. Method A: Bulk CSV upload with upserts
3. Method B: Sequential batch number generator
4. Method C: Live bench tap-to-enroll mode
5. Hardware tap verification and daily limit quotas
6. Calendar, Vendor, and Machine-filtered Excel (.xlsx) report export
"""
import pytest
import io
import csv
from datetime import datetime
from fastapi.testclient import TestClient
from src.main import app
from src.db.session import get_db, SessionLocal
from src.db.models.client import Client
from src.db.models.device import Device, DeviceType
from src.db.models.user import User
from src.db.models.rfid_vending import RFIDVendingCard, RFIDVendingLog
from src.core.security.tokens import create_access_token

client = TestClient(app)


@pytest.fixture(scope="module")
def setup_rfid_vending_data():
    db = SessionLocal()
    # 1. Ensure Client
    tenant = db.query(Client).filter(Client.client_code == "APEX_VEND").first()
    if not tenant:
        tenant = Client(name="Apex Vending Corp", client_code="APEX_VEND", contact_email="contact@apex.local", status="ACTIVE")
        db.add(tenant)
        db.flush()

    # 2. Ensure Device Type & Device
    dtype = db.query(DeviceType).filter(DeviceType.code == "VENDING_MACHINE").first()
    if not dtype:
        dtype = DeviceType(name="Smart Vending Machine", code="VENDING_MACHINE")
        db.add(dtype)
        db.flush()

    device = db.query(Device).filter(Device.device_id == "VM-RFID-001").first()
    if not device:
        device = Device(
            client_id=tenant.id,
            device_type_id=dtype.id,
            device_id="VM-RFID-001",
            hardware_id="HW-ESP32-V1",
            chip_id="CHIP-RFID-001",
            mac_address="24:6F:28:AB:CD:EF",
            factory_serial="SN-RFID-001",
            status="ACTIVE",
            is_online=True,
        )
        db.add(device)
        db.flush()

    # 3. Ensure User
    user = db.query(User).filter(User.username == "apex_admin").first()
    if not user:
        user = User(
            client_id=tenant.id,
            username="apex_admin",
            email="admin@apex.local",
            role="CLIENT_ADMIN",
            password_hash="fakehash",
            status="ACTIVE",
        )
        db.add(user)
        db.flush()

    db.commit()
    token = create_access_token(user_id=user.id, username=user.username, email=user.email, role=user.role, client_id=tenant.id)
    tenant_id = tenant.id
    dev_id = device.device_id
    db.close()

    yield {
        "tenant_id": tenant_id,
        "device_id": dev_id,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def test_crud_single_card(setup_rfid_vending_data):
    headers = setup_rfid_vending_data["headers"]
    dev_id = setup_rfid_vending_data["device_id"]

    # 1. Create card
    res = client.post(
        "/api/v1/rfid-vending/cards",
        json={
            "card_uid": "A1:B2:C3:D4",
            "username": "Ravi Shankar",
            "department": "Engineering",
            "device_id": dev_id,
            "daily_limit": 2,
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    card_id = res.json()["card_id"]

    # 2. List cards
    res_list = client.get("/api/v1/rfid-vending/cards", headers=headers)
    assert res_list.status_code == 200
    data = res_list.json()
    assert data["total"] >= 1
    found = any(c["card_uid"] == "A1B2C3D4" for c in data["cards"])
    assert found

    # 3. Update card
    res_up = client.put(
        f"/api/v1/rfid-vending/cards/{card_id}",
        json={"username": "Ravi Shankar (Updated)", "daily_limit": 3},
        headers=headers,
    )
    assert res_up.status_code == 200


def test_method_b_batch_generate_1000_cards(setup_rfid_vending_data):
    headers = setup_rfid_vending_data["headers"]
    dev_id = setup_rfid_vending_data["device_id"]

    # Generate 1,000 cards in single batch
    res = client.post(
        "/api/v1/rfid-vending/batch-generate",
        json={
            "device_id": dev_id,
            "prefix": "Staff-",
            "uid_prefix": "BATCH-",
            "start_num": 1,
            "end_num": 1000,
            "pad_digits": 4,
            "daily_limit": 1,
        },
        headers=headers,
    )
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["success"] is True
    assert result["created"] == 1000

    # Query 1,000 cards from list endpoint
    res_list = client.get("/api/v1/rfid-vending/cards?limit=1000", headers=headers)
    assert res_list.status_code == 200
    assert res_list.json()["total"] >= 1000


def test_method_a_bulk_csv_upload(setup_rfid_vending_data):
    headers = setup_rfid_vending_data["headers"]
    dev_id = setup_rfid_vending_data["device_id"]

    # Create CSV in-memory with multiple cards
    csv_buffer = io.StringIO()
    writer = csv.writer(csv_buffer)
    writer.writerow(["card_uid", "username", "department", "daily_limit", "is_active"])
    writer.writerow(["CSV001", "Bulk User 1", "Operations", "2", "TRUE"])
    writer.writerow(["CSV002", "Bulk User 2", "HR", "1", "TRUE"])
    writer.writerow(["CSV003", "Bulk User 3", "Finance", "5", "TRUE"])
    csv_bytes = csv_buffer.getvalue().encode("utf-8")

    files = {"file": ("bulk_test.csv", csv_bytes, "text/csv")}
    res = client.post(
        f"/api/v1/rfid-vending/bulk-upload?device_id={dev_id}",
        files=files,
        headers=headers,
    )
    assert res.status_code == 200, res.text
    result = res.json()
    assert result["success"] is True
    assert result["imported"] == 3


def test_method_c_live_tap_enroll_mode(setup_rfid_vending_data):
    headers = setup_rfid_vending_data["headers"]
    dev_id = setup_rfid_vending_data["device_id"]

    # 1. Turn enroll mode ON
    res_on = client.post(
        f"/api/v1/rfid-vending/devices/{dev_id}/enroll-mode",
        json={"enabled": True},
        headers=headers,
    )
    assert res_on.status_code == 200
    assert res_on.json()["enroll_mode"] is True

    # 2. Simulate hardware tapping an unregistered card on ESP32
    tap_res = client.post(
        "/api/v1/rfid-vending/verify-tap",
        json={"device_id": dev_id, "card_uid": "NEWTAG9988"},
    )
    assert tap_res.status_code == 200
    assert tap_res.json()["authorized"] is False
    assert tap_res.json()["status"] == "UNKNOWN_CARD"

    # 3. Web portal checks enroll status -> should see the newly captured card!
    poll_res = client.get(f"/api/v1/rfid-vending/devices/{dev_id}/enroll-status")
    assert poll_res.status_code == 200
    assert poll_res.json()["enroll_active"] is True
    assert poll_res.json()["last_uid"] == "NEWTAG9988"

    # 4. Turn enroll mode OFF
    res_off = client.post(
        f"/api/v1/rfid-vending/devices/{dev_id}/enroll-mode",
        json={"enabled": False},
        headers=headers,
    )
    assert res_off.status_code == 200
    assert res_off.json()["enroll_mode"] is False


def test_hardware_verify_tap_and_daily_limit(setup_rfid_vending_data):
    dev_id = setup_rfid_vending_data["device_id"]
    headers = setup_rfid_vending_data["headers"]

    # Register card with daily_limit = 1
    client.post(
        "/api/v1/rfid-vending/cards",
        json={
            "card_uid": "LIMIT-TAG-1",
            "username": "Limit Tester",
            "device_id": dev_id,
            "daily_limit": 1,
        },
        headers=headers,
    )

    # First tap: Should SUCCEED
    tap1 = client.post(
        "/api/v1/rfid-vending/verify-tap",
        json={"device_id": dev_id, "card_uid": "LIMIT-TAG-1"},
    )
    assert tap1.status_code == 200
    assert tap1.json()["authorized"] is True
    assert tap1.json()["status"] == "DISPENSED_SUCCESS"
    assert tap1.json()["used_today"] == 1

    # Second tap on same day: Should EXCEED LIMIT
    tap2 = client.post(
        "/api/v1/rfid-vending/verify-tap",
        json={"device_id": dev_id, "card_uid": "LIMIT-TAG-1"},
    )
    assert tap2.status_code == 200
    assert tap2.json()["authorized"] is False
    assert tap2.json()["status"] == "DAILY_LIMIT_EXCEEDED"


def test_device_1000_card_sync(setup_rfid_vending_data):
    dev_id = setup_rfid_vending_data["device_id"]
    res = client.get(f"/api/v1/rfid-vending/devices/{dev_id}/sync-cards")
    assert res.status_code == 200
    data = res.json()
    assert data["device_id"] == dev_id
    assert data["count"] >= 1000
    assert len(data["cards"]) >= 1000


def test_excel_and_csv_report_export(setup_rfid_vending_data):
    headers = setup_rfid_vending_data["headers"]
    dev_id = setup_rfid_vending_data["device_id"]
    today_str = datetime.utcnow().strftime("%Y-%m-%d")

    # 1. Fetch JSON reports
    res = client.get(
        f"/api/v1/rfid-vending/reports?start_date={today_str}&end_date={today_str}&device_id={dev_id}",
        headers=headers,
    )
    assert res.status_code == 200
    assert res.json()["total"] >= 2

    # 2. Export Excel (.xlsx)
    res_xlsx = client.get(
        f"/api/v1/rfid-vending/reports/export?start_date={today_str}&end_date={today_str}&device_id={dev_id}&format=xlsx",
        headers=headers,
    )
    assert res_xlsx.status_code == 200
    assert "application/vnd.openxmlformats" in res_xlsx.headers.get("content-type", "")
    assert len(res_xlsx.content) > 1000  # valid binary excel file

    # 3. Export CSV
    res_csv = client.get(
        f"/api/v1/rfid-vending/reports/export?start_date={today_str}&end_date={today_str}&device_id={dev_id}&format=csv",
        headers=headers,
    )
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers.get("content-type", "")
    assert b"log_id" in res_csv.content
