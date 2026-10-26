"""
Unit and Integration Tests for Remote Wi-Fi Credential Management.
Tests:
1. Online Wi-Fi credentials update via Manufacturer Superadmin / Admin.
2. Online Wi-Fi credentials update via Client / Vendor Admin for assigned fleet.
3. Multi-tenant isolation: Vendor is blocked from updating another tenant's Wi-Fi.
4. Edge ESP32 device retrieval via /device-gateway/wifi-credentials and /device-gateway/config.
5. Configuration version increment and acknowledgment synchronization.
6. Audit log trail recording WIFI_CREDENTIALS_UPDATED.
"""
import sys
import os
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import app
from src.db.session import SessionLocal, engine
from src.db.base import Base
from src.db.seed import seed_database
from src.db.models.audit import AuditLog
from src.db.models.device import Device

client = TestClient(app)

VM1_CHIP_ID = "ESP32-S3-0x3C8427F8B101"
VM1_MAC_ADDR = "3C:84:27:F8:B1:01"
VM1_TOKEN = "dev_token_VM-000001"


@pytest.fixture(scope="module", autouse=True)
def setup_database():
    """Ensure database has fresh schema and seed data for Wi-Fi tests."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_database(session)
    finally:
        session.close()


def get_token(username: str, password: str) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


def get_device_token(device_id: str, chip_id: str, mac_addr: str, token: str) -> str:
    resp = client.post(
        "/api/v1/device-gateway/authenticate",
        json={
            "device_id": device_id,
            "chip_id": chip_id,
            "mac_address": mac_addr,
            "device_token": token,
            "firmware_version": "v1.0.0",
            "boot_count": 1,
        },
    )
    assert resp.status_code == 200, f"Device auth failed: {resp.text}"
    return resp.json()["session_token"]


def test_manufacturer_update_device_wifi():
    """Manufacturer admin can remotely configure Wi-Fi credentials for any device."""
    admin_token = get_token("admin", "Admin@SecurePlatform2026!")

    # 1. Update Wi-Fi credentials
    put_resp = client.put(
        "/api/v1/devices/VM-000001/wifi",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "wifi_ssid": "Factory_Lab_WiFi_5G",
            "wifi_password": "LabSecurePassword123!",
        },
    )
    assert put_resp.status_code == 200, put_resp.text
    data = put_resp.json()
    assert data["device_id"] == "VM-000001"
    assert data["wifi_ssid"] == "Factory_Lab_WiFi_5G"
    assert data["has_password"] is True
    assert data["is_synced"] is False
    assert data["config_version"] >= 2

    # 2. Get Wi-Fi metadata
    get_resp = client.get(
        "/api/v1/devices/VM-000001/wifi",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert get_resp.status_code == 200
    meta = get_resp.json()
    assert meta["wifi_ssid"] == "Factory_Lab_WiFi_5G"
    assert meta["has_password"] is True


def test_vendor_update_own_device_wifi():
    """Client / Vendor Admin can change Wi-Fi credentials for their assigned fleet."""
    apex_token = get_token("apex_admin", "Apex@Admin2026!")

    put_resp = client.put(
        "/api/v1/devices/VM-000001/wifi",
        headers={"Authorization": f"Bearer {apex_token}"},
        json={
            "wifi_ssid": "Apex_Retail_Floor_2",
            "wifi_password": "ApexNewWiFiSecret2026",
        },
    )
    assert put_resp.status_code == 200, put_resp.text
    data = put_resp.json()
    assert data["wifi_ssid"] == "Apex_Retail_Floor_2"
    assert data["has_password"] is True


def test_vendor_tenant_isolation_blocked_from_other_devices():
    """Vendor Admin cannot change Wi-Fi credentials for a machine belonging to another vendor."""
    metro_token = get_token("metro_admin", "Metro@Retail2026!")

    # VM-000001 is assigned to Apex Vending, NOT Metro Retail
    put_resp = client.put(
        "/api/v1/devices/VM-000001/wifi",
        headers={"Authorization": f"Bearer {metro_token}"},
        json={
            "wifi_ssid": "Unauthorized_WiFi",
            "wifi_password": "evilpassword",
        },
    )
    assert put_resp.status_code in (403, 404), f"Expected 403/404, got {put_resp.status_code}"


def test_edge_device_pulls_wifi_credentials_and_acknowledges():
    """ESP32 hardware node pulls the new Wi-Fi credentials and acknowledges sync."""
    dev_jwt = get_device_token("VM-000001", VM1_CHIP_ID, VM1_MAC_ADDR, VM1_TOKEN)

    # 1. Edge device calls /device-gateway/wifi-credentials
    wifi_resp = client.get(
        "/api/v1/device-gateway/wifi-credentials",
        headers={"Authorization": f"Bearer {dev_jwt}"},
    )
    assert wifi_resp.status_code == 200
    w_data = wifi_resp.json()
    assert w_data["wifi_ssid"] == "Apex_Retail_Floor_2"
    assert w_data["wifi_password"] == "ApexNewWiFiSecret2026"

    # 2. Edge device calls /device-gateway/config
    cfg_resp = client.get(
        "/api/v1/device-gateway/config",
        headers={"Authorization": f"Bearer {dev_jwt}"},
    )
    assert cfg_resp.status_code == 200
    cfg_data = cfg_resp.json()
    assert cfg_data["settings"]["wifi_ssid"] == "Apex_Retail_Floor_2"
    assert cfg_data["settings"]["wifi_password"] == "ApexNewWiFiSecret2026"
    checksum = cfg_data["checksum"]
    applied_ver = cfg_data["config_version"]

    # 3. Edge commits to Flash NVS and sends ACK
    ack_resp = client.post(
        "/api/v1/device-gateway/config/ack",
        headers={"Authorization": f"Bearer {dev_jwt}"},
        json={
            "device_id": "VM-000001",
            "applied_version": applied_ver,
            "checksum": checksum,
            "status": "SUCCESS",
        },
    )
    assert ack_resp.status_code == 200
    assert ack_resp.json()["is_synced"] is True


def test_wifi_update_audit_log_persisted():
    """Audit log records specific WIFI_CREDENTIALS_UPDATED action."""
    session = SessionLocal()
    try:
        audit_records = session.query(AuditLog).filter_by(
            action="WIFI_CREDENTIALS_UPDATED"
        ).all()
        assert len(audit_records) >= 1
        latest = audit_records[-1]
        assert "Apex_Retail_Floor_2" in str(latest.new_state)
    finally:
        session.close()
