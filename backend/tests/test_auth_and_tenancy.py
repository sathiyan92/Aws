"""
Comprehensive Unit & Integration Test Suite for Phase 3:
Authentication and Multi-Tenant Authorization.
Tests RBAC guards, JWT token lifecycles, tenant boundary enforcement, and backend module guards.
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
from src.db.models import Client, User, Device, DeviceModule, DeviceType
from src.core.security.hashing import hash_password

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Initialize schema, run seed pipeline, and create a second tenant for isolation testing."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        seed_database(session)

        # Create a second distinct client tenant (Tenant B) to test cross-tenant isolation
        tenant_b = Client(
            client_code="CLIENT_BETA",
            name="Beta Retails Ltd",
            contact_email="admin@betaretails.local",
            status="ACTIVE",
        )
        session.add(tenant_b)
        session.flush()

        # User for Tenant B
        user_b = User(
            client_id=tenant_b.id,
            username="beta_admin",
            email="admin@betaretails.local",
            password_hash=hash_password("Beta@Admin2026!"),
            full_name="Beta Admin User",
            role="CLIENT_ADMIN",
            status="ACTIVE",
        )
        session.add(user_b)
        session.flush()

        # Device for Tenant B
        vending_type = session.query(DeviceType).filter_by(code="VENDING_MACHINE").first()
        dev_b = Device(
            device_id="VM-000099",
            client_id=tenant_b.id,
            device_type_id=vending_type.id,
            hardware_id="HW-ESP32S3-V1.2",
            chip_id="ESP32-S3-0x99BETA",
            mac_address="3C:84:27:99:BE:01",
            factory_serial="MFG-2026-VM-099",
            status="ACTIVE",
            is_online=True,
        )
        session.add(dev_b)
        session.flush()

        session.add(DeviceModule(device_id=dev_b.id, module_code="QR_PAYMENT", is_enabled=True))
        session.commit()
    finally:
        session.close()


def test_health_endpoint():
    """Verify system health endpoint operates without authentication."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_manufacturer_admin_login():
    """Verify Manufacturer Admin login returns valid JWT with global scope (client_id=NULL)."""
    response = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": "Admin@SecurePlatform2026!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["user"]["role"] == "MANUFACTURER_ADMIN"
    assert data["user"]["client_id"] is None


def test_client_admin_login():
    """Verify Client Admin login returns valid JWT with tenant-scoped client_id."""
    response = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "apex_admin", "password": "Apex@Admin2026!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["user"]["role"] == "CLIENT_ADMIN"
    assert data["user"]["client_id"] is not None


def test_login_invalid_credentials():
    """Verify that wrong password returns HTTP 401 NOT_AUTHENTICATED."""
    response = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": "WrongPassword!"},
    )
    assert response.status_code == 401
    assert response.json()["error_code"] == "NOT_AUTHENTICATED"


def test_protected_route_requires_token():
    """Verify unauthenticated request to /auth/me returns 401."""
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    assert response.json()["error_code"] == "NOT_AUTHENTICATED"


def test_auth_me_returns_profile():
    """Verify Bearer token correctly populates user profile on /auth/me."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "apex_admin", "password": "Apex@Admin2026!"},
    )
    token = login_resp.json()["access_token"]

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["username"] == "apex_admin"


def test_token_refresh_flow():
    """Verify refresh token can generate a new access token."""
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": "Admin@SecurePlatform2026!"},
    )
    refresh_tok = login_resp.json()["refresh_token"]

    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_tok},
    )
    assert refresh_resp.status_code == 200
    assert "access_token" in refresh_resp.json()


def test_strict_tenant_isolation_boundary():
    """
    CRITICAL MULTI-TENANT TEST:
    Apex Admin belongs to Tenant A.
    Attempting to access Tenant B's devices must return HTTP 403 TENANT_ISOLATION_VIOLATION.
    A client must NEVER access another client's devices or data.
    """
    session = SessionLocal()
    try:
        tenant_b = session.query(Client).filter_by(client_code="CLIENT_BETA").first()
        tenant_a = session.query(Client).filter_by(client_code="CLIENT_APEX").first()
    finally:
        session.close()

    # Log in as Apex Admin (Tenant A)
    apex_token = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "apex_admin", "password": "Apex@Admin2026!"},
    ).json()["access_token"]

    # 1. Apex Admin queries own tenant devices -> SUCCESS (200 OK)
    resp_own = client.get(
        f"/api/v1/tenants/{tenant_a.id}/devices",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp_own.status_code == 200
    assert resp_own.json()["devices_count"] >= 3

    # 2. Apex Admin attempts to query Tenant B's devices -> REJECTED (403 Forbidden)
    resp_foreign = client.get(
        f"/api/v1/tenants/{tenant_b.id}/devices",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp_foreign.status_code == 403
    assert resp_foreign.json()["error_code"] == "TENANT_ISOLATION_VIOLATION"


def test_manufacturer_admin_global_visibility():
    """Verify that Manufacturer Super-Admin can inspect devices of any client."""
    session = SessionLocal()
    try:
        tenant_a = session.query(Client).filter_by(client_code="CLIENT_APEX").first()
        tenant_b = session.query(Client).filter_by(client_code="CLIENT_BETA").first()
    finally:
        session.close()

    # Log in as Manufacturer Admin
    mfg_token = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": "Admin@SecurePlatform2026!"},
    ).json()["access_token"]

    # Manufacturer inspects Tenant A -> 200 OK
    resp_a = client.get(
        f"/api/v1/tenants/{tenant_a.id}/devices",
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert resp_a.status_code == 200

    # Manufacturer inspects Tenant B -> 200 OK
    resp_b = client.get(
        f"/api/v1/tenants/{tenant_b.id}/devices",
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert resp_b.status_code == 200


def test_rbac_manufacturer_admin_only_endpoint():
    """Verify RBAC guard: Client Admin cannot access Manufacturer-only endpoints."""
    apex_token = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "apex_admin", "password": "Apex@Admin2026!"},
    ).json()["access_token"]

    mfg_token = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": "Admin@SecurePlatform2026!"},
    ).json()["access_token"]

    # Client Admin attempts platform stats -> 403 Forbidden
    resp_denied = client.get(
        "/api/v1/manufacturer/platform-stats",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp_denied.status_code == 403
    assert resp_denied.json()["error_code"] == "FORBIDDEN_ACCESS"

    # Manufacturer Admin accesses platform stats -> 200 OK
    resp_allowed = client.get(
        "/api/v1/manufacturer/platform-stats",
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert resp_allowed.status_code == 200
    assert resp_allowed.json()["access"] == "UNRESTRICTED_GLOBAL"


def test_backend_module_authorization_policy():
    """
    CRITICAL MODULE GUARD TEST:
    Backend must strictly enforce module authorization, not relying on frontend hiding alone.
    Device VM-000001: QR_PAYMENT is ENABLED, COIN_PAYMENT is DISABLED.
    Device VM-000002: QR_PAYMENT is DISABLED, COIN_PAYMENT is ENABLED.
    """
    apex_token = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "apex_admin", "password": "Apex@Admin2026!"},
    ).json()["access_token"]

    # VM-000001: Access QR (Allowed: 200 OK)
    resp_qr_ok = client.get(
        "/api/v1/devices/VM-000001/modules/QR_PAYMENT/access",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp_qr_ok.status_code == 200
    assert resp_qr_ok.json()["status"] == "granted"

    # VM-000001: Access Coin (Disabled on device -> 403 MODULE_DISABLED)
    resp_coin_blocked = client.get(
        "/api/v1/devices/VM-000001/modules/COIN_PAYMENT/access",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp_coin_blocked.status_code == 403
    assert resp_coin_blocked.json()["error_code"] == "MODULE_DISABLED_FOR_DEVICE"

    # VM-000002: Access Coin (Allowed: 200 OK)
    resp_vm2_coin_ok = client.get(
        "/api/v1/devices/VM-000002/modules/COIN_PAYMENT/access",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp_vm2_coin_ok.status_code == 200

    # VM-000002: Access QR (Disabled on device -> 403 MODULE_DISABLED)
    resp_vm2_qr_blocked = client.get(
        "/api/v1/devices/VM-000002/modules/QR_PAYMENT/access",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp_vm2_qr_blocked.status_code == 403
    assert resp_vm2_qr_blocked.json()["error_code"] == "MODULE_DISABLED_FOR_DEVICE"


def test_device_cross_tenant_access_blocked():
    """
    Apex Admin attempts to access a device (VM-000099) belonging to Tenant B.
    Must return 403 TENANT_ISOLATION_VIOLATION.
    """
    apex_token = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "apex_admin", "password": "Apex@Admin2026!"},
    ).json()["access_token"]

    resp = client.get(
        "/api/v1/devices/VM-000099/modules/QR_PAYMENT/access",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "TENANT_ISOLATION_VIOLATION"
