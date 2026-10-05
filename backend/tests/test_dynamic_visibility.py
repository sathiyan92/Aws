"""
Unit and Integration Tests for Phase 6:
Client Portal & Dynamic Feature Visibility.
Tests dynamic module capabilities, client portal static assets, authorized module access,
and strict server-side policy enforcement (HTTP 403 rejection for disabled modules and cross-tenant access).
"""
import sys
import os
import pytest
from fastapi.testclient import TestClient

# Add backend root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import app
from src.db.session import SessionLocal, engine
from src.db.base import Base
from src.db.seed import seed_database
from src.db.models import Device, DeviceModule

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure database is seeded with initial clients, devices, and modules."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_database(session)
    finally:
        session.close()


def get_token(username: str, password: str) -> str:
    """Helper to authenticate and retrieve access token."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


@pytest.fixture
def apex_admin_token() -> str:
    """Apex Vending Solutions Admin Token."""
    return get_token("apex_admin", "Apex@Admin2026!")


@pytest.fixture
def metro_admin_token() -> str:
    """Metro Retail Networks Admin Token."""
    return get_token("metro_admin", "Metro@Retail2026!")


def test_client_portal_static_assets_served():
    """Verify FastAPI serves the static Client Portal HTML, CSS, and JS assets."""
    r_html = client.get("/client-portal/index.html")
    assert r_html.status_code == 200
    assert "Apex Client Portal" in r_html.text
    assert "Dynamic Feature Visibility" in r_html.text

    r_css = client.get("/client-portal/styles.css")
    assert r_css.status_code == 200
    assert ".dynamic-hidden" in r_css.text

    r_js = client.get("/client-portal/app.js")
    assert r_js.status_code == 200
    assert "dynamic-hidden" in r_js.text
    assert "handleSimulateSecurityAttack" in r_js.text


def test_fleet_capabilities_multi_tenant_isolation(apex_admin_token, metro_admin_token):
    """
    Verify client tenant only sees their own assigned devices and accurate module flags.
    """
    # 1. Apex Admin fleet check
    resp_apex = client.get(
        "/api/v1/vending/fleet-capabilities",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp_apex.status_code == 200
    apex_devices = resp_apex.json()

    apex_device_ids = [d["device_id"] for d in apex_devices]
    assert "VM-000001" in apex_device_ids
    assert "VM-000002" in apex_device_ids
    assert "VM-000003" in apex_device_ids
    assert "RFID-000001" in apex_device_ids
    # Crucial tenant isolation check: Metro's devices must NOT be present
    assert "VM-000004" not in apex_device_ids
    assert "RFID-000002" not in apex_device_ids

    # 2. Metro Admin fleet check
    resp_metro = client.get(
        "/api/v1/vending/fleet-capabilities",
        headers={"Authorization": f"Bearer {metro_admin_token}"},
    )
    assert resp_metro.status_code == 200
    metro_devices = resp_metro.json()
    metro_device_ids = [d["device_id"] for d in metro_devices]
    assert "VM-000004" in metro_device_ids
    assert "RFID-000002" in metro_device_ids
    assert "VM-000001" not in metro_device_ids


def test_dynamic_module_capabilities_breakdown(apex_admin_token):
    """
    Verify per-device dynamic capability flags for VM-000001, VM-000002, VM-000003, and RFID-000001.
    """
    resp = client.get(
        "/api/v1/vending/fleet-capabilities",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp.status_code == 200
    fleet_map = {d["device_id"]: d for d in resp.json()}

    # VM-000001: QR Only
    vm1 = fleet_map["VM-000001"]
    assert vm1["has_qr_payment"] is True
    assert vm1["has_coin_payment"] is False
    assert vm1["has_rfid_access"] is False

    # VM-000002: Coin Only
    vm2 = fleet_map["VM-000002"]
    assert vm2["has_qr_payment"] is False
    assert vm2["has_coin_payment"] is True
    assert vm2["has_rfid_access"] is False

    # VM-000003: Hybrid (QR + Coin)
    vm3 = fleet_map["VM-000003"]
    assert vm3["has_qr_payment"] is True
    assert vm3["has_coin_payment"] is True
    assert vm3["has_rfid_access"] is False

    # RFID-000001: RFID Only
    rfid1 = fleet_map["RFID-000001"]
    assert rfid1["has_qr_payment"] is False
    assert rfid1["has_coin_payment"] is False
    assert rfid1["has_rfid_access"] is True


def test_legitimate_access_to_enabled_modules(apex_admin_token):
    """
    Verify 200 OK access when requesting endpoints for hardware modules that are enabled.
    """
    # 1. VM-000001 has QR_PAYMENT -> Access QR settings
    r_qr = client.get(
        "/api/v1/vending/VM-000001/qr/settings",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_qr.status_code == 200
    assert r_qr.json()["device_id"] == "VM-000001"
    assert "upi_merchant_vpa" in r_qr.json()

    # 2. VM-000002 has COIN_PAYMENT -> Access Coin settings
    r_coin = client.get(
        "/api/v1/vending/VM-000002/coins/settings",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_coin.status_code == 200
    assert r_coin.json()["device_id"] == "VM-000002"
    assert "pulse_mappings" in r_coin.json()

    # 3. RFID-000001 has RFID_ACCESS -> Access RFID cards
    r_rfid = client.get(
        "/api/v1/rfid/RFID-000001/cards",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_rfid.status_code == 200
    assert isinstance(r_rfid.json(), list)


def test_server_side_policy_enforcement_blocks_disabled_modules(apex_admin_token):
    """
    CRITICAL SECURITY TEST:
    Verify that if a client attempts to access endpoints for modules that are disabled on that machine,
    the backend strictly rejects the request with HTTP 403 and error code MODULE_DISABLED_FOR_DEVICE.
    """
    # 1. Try to access Coin settings on VM-000001 (QR only)
    r_coin_on_vm1 = client.get(
        "/api/v1/vending/VM-000001/coins/settings",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_coin_on_vm1.status_code == 403
    err_coin = r_coin_on_vm1.json()
    assert err_coin["error_code"] == "MODULE_DISABLED_FOR_DEVICE"
    assert "COIN_PAYMENT" in err_coin["message"]
    assert "VM-000001" in err_coin["message"]

    # 2. Try to access QR settings on VM-000002 (Coin only)
    r_qr_on_vm2 = client.get(
        "/api/v1/vending/VM-000002/qr/settings",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_qr_on_vm2.status_code == 403
    err_qr = r_qr_on_vm2.json()
    assert err_qr["error_code"] == "MODULE_DISABLED_FOR_DEVICE"
    assert "QR_PAYMENT" in err_qr["message"]
    assert "VM-000002" in err_qr["message"]

    # 3. Try to access RFID cards on VM-000001 (Vending machine, no RFID)
    r_rfid_on_vm1 = client.get(
        "/api/v1/rfid/VM-000001/cards",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_rfid_on_vm1.status_code == 403
    err_rfid = r_rfid_on_vm1.json()
    assert err_rfid["error_code"] == "MODULE_DISABLED_FOR_DEVICE"
    assert "RFID_ACCESS" in err_rfid["message"]

    # 4. Try to access Vending QR settings on RFID-000001 (Attendance reader, no QR)
    r_qr_on_rfid1 = client.get(
        "/api/v1/vending/RFID-000001/qr/settings",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_qr_on_rfid1.status_code == 403


def test_cross_tenant_device_access_strictly_forbidden(apex_admin_token, metro_admin_token):
    """
    CRITICAL MULTI-TENANT ISOLATION TEST:
    Verify that a client tenant cannot access or configure another tenant's hardware,
    even if the module is enabled on that machine.
    """
    # Apex admin attempts to read QR settings of VM-000004 (owned by Metro Retail)
    resp = client.get(
        "/api/v1/vending/VM-000004/qr/settings",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp.status_code == 403
    assert "Access denied" in resp.json()["message"]

    # Metro admin attempts to read Coin settings of VM-000002 (owned by Apex)
    resp2 = client.get(
        "/api/v1/vending/VM-000002/coins/settings",
        headers={"Authorization": f"Bearer {metro_admin_token}"},
    )
    assert resp2.status_code == 403
    assert "Access denied" in resp2.json()["message"]


def test_configuration_updates_and_version_bumping(apex_admin_token):
    """
    Verify that updating module parameters increments device.current_config_version
    without requiring firmware recompilation.
    """
    # Initial config version of VM-000001
    cap_before = client.get(
        "/api/v1/vending/fleet-capabilities",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    ).json()
    vm1_before = next(d for d in cap_before if d["device_id"] == "VM-000001")
    initial_ver = vm1_before["config_version"]

    # Update QR settings
    r_update = client.put(
        "/api/v1/vending/VM-000001/qr/settings",
        json={
            "upi_merchant_vpa": "apex.ops.new@icici",
            "qr_timeout_seconds": 240,
            "dynamic_pricing_enabled": True,
        },
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_update.status_code == 200
    assert r_update.json()["upi_merchant_vpa"] == "apex.ops.new@icici"
    assert r_update.json()["qr_timeout_seconds"] == 240

    # Verify version was incremented
    cap_after = client.get(
        "/api/v1/vending/fleet-capabilities",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    ).json()
    vm1_after = next(d for d in cap_after if d["device_id"] == "VM-000001")
    assert vm1_after["config_version"] == initial_ver + 1


def test_rfid_card_enrollment_and_attendance_retrieval(apex_admin_token):
    """
    Verify enrolling a new RFID card on RFID-000001 and checking card list.
    """
    r_enroll = client.post(
        "/api/v1/rfid/RFID-000001/cards",
        json={
            "card_uid": "AA:BB:CC:DD:01",
            "employee_name": "Vikram Sethi",
            "department": "Engineering Operations",
        },
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_enroll.status_code == 200
    card_data = r_enroll.json()
    assert card_data["card_uid"] == "AA:BB:CC:DD:01"
    assert card_data["employee_name"] == "Vikram Sethi"
    assert card_data["status"] == "ACTIVE"

    # Verify card is returned in card list
    r_list = client.get(
        "/api/v1/rfid/RFID-000001/cards",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r_list.status_code == 200
    uids = [c["card_uid"] for c in r_list.json()]
    assert "AA:BB:CC:DD:01" in uids
