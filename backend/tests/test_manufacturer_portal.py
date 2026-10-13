"""
Unit and Integration Tests for Phase 5:
Manufacturer Operations Portal & Administration Endpoints.
Tests static asset serving, platform analytics telemetry, and audit trail inspection.
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
from src.db.models import Client, User, Device, AuditLog

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_portal_database():
    """Ensure database is seeded with initial clients, devices, and audit records."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_database(session)
    finally:
        session.close()


def get_mfg_token() -> str:
    """Helper to authenticate as Manufacturer Admin."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": "Admin@SecurePlatform2026!"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_manufacturer_portal_static_assets_served():
    """Verify FastAPI serves the static Manufacturer Portal HTML, CSS, and JS assets."""
    r_html = client.get("/portal/index.html")
    assert r_html.status_code == 200
    assert "Manufacturer Operations Portal" in r_html.text
    assert "Fleet Command" in r_html.text

    r_css = client.get("/portal/styles.css")
    assert r_css.status_code == 200
    assert "--primary" in r_css.text

    r_js = client.get("/portal/app.js")
    assert r_js.status_code == 200
    assert "bootstrapPortal" in r_js.text


def test_platform_statistics_endpoint():
    """Verify /api/v1/manufacturer/platform-stats returns rich fleet telemetry."""
    token = get_mfg_token()
    resp = client.get(
        "/api/v1/manufacturer/platform-stats",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()

    assert "devices_count" in data
    assert "online_devices_count" in data
    assert "clients_count" in data
    assert "status_breakdown" in data
    assert "product_type_breakdown" in data
    assert "module_breakdown" in data
    assert "recent_audits" in data

    assert data["devices_count"] >= 4
    assert data["clients_count"] >= 1
    assert data["product_type_breakdown"]["VENDING_MACHINE"] >= 3
    assert data["product_type_breakdown"]["RFID_ATTENDANCE"] >= 1
    assert data["module_breakdown"]["QR_PAYMENT"] >= 2


def test_audit_logs_endpoint():
    """Verify /api/v1/audit-logs returns immutable audit records for super-admin."""
    token = get_mfg_token()
    resp = client.get(
        "/api/v1/audit-logs?limit=10",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "logs" in data
    assert len(data["logs"]) >= 1

    first_log = data["logs"][0]
    assert "action" in first_log
    assert "entity_type" in first_log
    assert "created_at" in first_log


def test_audit_logs_unauthorized_for_client_admin():
    """Verify Client Admin cannot access global audit logs (RBAC protection)."""
    # Login as client admin
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "apex_admin", "password": "Apex@Admin2026!"},
    )
    assert resp.status_code == 200
    client_token = resp.json()["access_token"]

    r_denied = client.get(
        "/api/v1/audit-logs",
        headers={"Authorization": f"Bearer {client_token}"},
    )
    assert r_denied.status_code == 403
    assert r_denied.json()["error_code"] == "FORBIDDEN_ACCESS"


def test_manufacturer_portal_edit_and_delete_device():
    """Verify portal hardware update, deletion, and resultant audit trail."""
    token = get_mfg_token()

    # Provision a node to test portal lifecycle operations
    prov_res = client.post(
        "/api/v1/devices",
        json={
            "device_type_code": "VENDING_MACHINE",
            "hardware_id": "HW-ESP32S3-V1.2",
            "chip_id": "ESP32-S3-0xPORTALTEST",
            "mac_address": "3C:84:27:00:11:22",
            "factory_serial": "MFG-2026-PORTAL-01",
            "initial_modules": {"QR_PAYMENT": True},
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert prov_res.status_code == 200
    dev_id = prov_res.json()["device_id"]

    # 1. Edit hardware details
    edit_res = client.put(
        f"/api/v1/devices/{dev_id}",
        json={
            "hardware_id": "HW-ESP32S3-V2.1-REVISION",
            "status": "MAINTENANCE",
            "current_firmware_version": "v2.0.1",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert edit_res.status_code == 200
    assert edit_res.json()["hardware_id"] == "HW-ESP32S3-V2.1-REVISION"
    assert edit_res.json()["status"] == "MAINTENANCE"
    assert edit_res.json()["current_firmware_version"] == "v2.0.1"

    # 2. Delete device
    del_res = client.delete(
        f"/api/v1/devices/{dev_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 200
    assert del_res.json()["status"] == "deleted"

    # 3. Check audit trail recorded DEVICE_HARDWARE_UPDATED and DEVICE_DELETED
    audit_res = client.get(
        "/api/v1/audit-logs?limit=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert audit_res.status_code == 200
    actions = [log["action"] for log in audit_res.json()["logs"]]
    assert "DEVICE_DELETED" in actions
    assert "DEVICE_HARDWARE_UPDATED" in actions

