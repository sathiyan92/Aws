"""
Comprehensive Unit & Integration Test Suite for Phase 4:
Device Lifecycle & Fleet Management.
Tests hardware provisioning, Device ID auto-naming, client assignment, module toggles,
configuration version bumping, and multi-tenant fleet isolation.
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
from src.db.models import Client, User, Device, DeviceModule, DeviceType, DeviceConfig, ConfigurationVersion
from src.core.security.hashing import hash_password

client = TestClient(app)


@pytest.fixture(scope="session", autouse=True)
def setup_device_test_database():
    """Initialize schema, run seed pipeline, and create distinct client tenants."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    session = SessionLocal()
    try:
        seed_database(session)

        # Create Tenant B for multi-tenant isolation testing
        tenant_b = Client(
            client_code="CLIENT_BETA",
            name="Beta Retailers Ltd",
            contact_email="admin@betaretail.local",
            status="ACTIVE",
        )
        session.add(tenant_b)
        session.flush()

        user_b = User(
            client_id=tenant_b.id,
            username="beta_admin",
            email="admin@betaretail.local",
            password_hash=hash_password("Beta@Admin2026!"),
            full_name="Beta Tenant Admin",
            role="CLIENT_ADMIN",
            status="ACTIVE",
        )
        session.add(user_b)
        session.flush()

        # Device assigned to Tenant B
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


def get_token(username: str, password: str) -> str:
    """Helper to authenticate and fetch access token."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


def test_list_supported_device_types():
    """Verify supported device types (VENDING_MACHINE, RFID_ATTENDANCE) can be queried."""
    mfg_token = get_token("admin", "Admin@SecurePlatform2026!")
    resp = client.get(
        "/api/v1/devices/types",
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert resp.status_code == 200
    types = {t["code"]: t for t in resp.json()}
    assert "VENDING_MACHINE" in types
    assert "RFID_ATTENDANCE" in types
    assert "QR_PAYMENT" in types["VENDING_MACHINE"]["supported_modules"]


def test_manufacturer_registers_vending_machine_auto_naming():
    """
    Verify Manufacturer registers new hardware and system auto-generates sequential Device ID:
    Seed has VM-000001, VM-000002, VM-000003, VM-000099.
    Next sequential ID will be VM-000100.
    """
    mfg_token = get_token("admin", "Admin@SecurePlatform2026!")
    payload = {
        "device_type_code": "VENDING_MACHINE",
        "hardware_id": "HW-ESP32S3-V1.2",
        "chip_id": "ESP32-S3-0xNEWVM100",
        "mac_address": "3C:84:27:00:01:00",
        "factory_serial": "MFG-2026-VM-100",
        "initial_modules": {"QR_PAYMENT": True, "COIN_PAYMENT": False, "RFID_ACCESS": False},
    }
    resp = client.post(
        "/api/v1/devices",
        json=payload,
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["device_id"] == "VM-000100"
    assert data["status"] == "PROVISIONED"
    assert data["client_id"] is None
    assert data["current_config_version"] == 1

    # Verify modules
    mods = {m["module_code"]: m["is_enabled"] for m in data["modules"]}
    assert mods["QR_PAYMENT"] is True
    assert mods["COIN_PAYMENT"] is False


def test_manufacturer_registers_rfid_terminal_auto_naming():
    """Verify RFID device registration auto-generates RFID-000002."""
    mfg_token = get_token("admin", "Admin@SecurePlatform2026!")
    payload = {
        "device_type_code": "RFID_ATTENDANCE",
        "hardware_id": "HW-ESP32-RFID-V1.0",
        "chip_id": "ESP32-0xNEWRFID02",
        "mac_address": "5C:84:27:00:00:02",
        "factory_serial": "MFG-2026-RFID-002",
        "initial_modules": {"RFID_ACCESS": True, "OFFLINE_SYNC": True},
    }
    resp = client.post(
        "/api/v1/devices",
        json=payload,
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["device_id"] in ["RFID-000002", "RFID-000003"]
    assert resp.json()["device_type_code"] == "RFID_ATTENDANCE"


def test_client_admin_cannot_register_device():
    """Verify Client Admin cannot call device registration (RBAC protection)."""
    apex_token = get_token("apex_admin", "Apex@Admin2026!")
    payload = {
        "device_type_code": "VENDING_MACHINE",
        "hardware_id": "HW-ESP32S3-V1.2",
        "chip_id": "ESP32-S3-0xROGUE",
        "mac_address": "3C:84:27:FF:FF:FF",
        "factory_serial": "MFG-ROGUE-001",
    }
    resp = client.post(
        "/api/v1/devices",
        json=payload,
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN_ACCESS"


def test_duplicate_hardware_identifiers_rejected():
    """Verify registering duplicate MAC or chip ID raises 400 Bad Request."""
    mfg_token = get_token("admin", "Admin@SecurePlatform2026!")
    # Attempt duplicate MAC of VM-000100
    payload = {
        "device_type_code": "VENDING_MACHINE",
        "hardware_id": "HW-ESP32S3-V1.2",
        "chip_id": "ESP32-S3-0xUNIQUE123",
        "mac_address": "3C:84:27:00:01:00",  # Duplicate MAC
        "factory_serial": "MFG-2026-UNIQUE-SERIAL",
    }
    resp = client.post(
        "/api/v1/devices",
        json=payload,
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert resp.status_code == 400
    assert "already registered" in resp.json()["message"]


def test_manufacturer_assigns_and_unassigns_device():
    """Verify Manufacturer assigns device to client tenant, then unassigns back to inventory."""
    mfg_token = get_token("admin", "Admin@SecurePlatform2026!")
    session = SessionLocal()
    try:
        apex_client = session.query(Client).filter_by(client_code="CLIENT_APEX").first()
        client_id = apex_client.id
    finally:
        session.close()

    # 1. Assign VM-000100 to Client Apex
    assign_resp = client.post(
        "/api/v1/devices/VM-000100/assign",
        json={"client_id": client_id},
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert assign_resp.status_code == 200
    assert assign_resp.json()["client_id"] == client_id
    assert assign_resp.json()["status"] == "ASSIGNED"

    # 2. Unassign VM-000100 back to factory inventory
    unassign_resp = client.post(
        "/api/v1/devices/VM-000100/assign",
        json={"client_id": None},
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert unassign_resp.status_code == 200
    assert unassign_resp.json()["client_id"] is None
    assert unassign_resp.json()["status"] == "PROVISIONED"


def test_manufacturer_toggles_hardware_module_bumps_config_version():
    """
    Verify Manufacturer toggles module on a machine:
    - Module status changes.
    - Configuration version automatically increments (v1 -> v2).
    - Active config payload is updated with new version.
    - ConfigurationVersion history record is added.
    """
    mfg_token = get_token("admin", "Admin@SecurePlatform2026!")

    # Check initial config version of VM-000001
    initial_resp = client.get(
        "/api/v1/devices/VM-000001",
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert initial_resp.status_code == 200
    v_init = initial_resp.json()["current_config_version"]

    # Toggle COIN_PAYMENT = True on VM-000001 (was False in seed)
    toggle_resp = client.put(
        "/api/v1/devices/VM-000001/modules",
        json={"module_code": "COIN_PAYMENT", "is_enabled": True},
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert toggle_resp.status_code == 200
    data = toggle_resp.json()
    assert data["current_config_version"] == v_init + 1
    coin_mod = next(m for m in data["modules"] if m["module_code"] == "COIN_PAYMENT")
    assert coin_mod["is_enabled"] is True

    # Verify ConfigurationVersion record in database
    session = SessionLocal()
    try:
        dev = session.query(Device).filter_by(device_id="VM-000001").first()
        assert dev.current_config_version == v_init + 1
        assert dev.config.active_version == v_init + 1
        assert dev.config.is_synced is False  # Awaiting edge sync
        history_entry = session.query(ConfigurationVersion).filter_by(
            device_id=dev.id,
            version_number=v_init + 1,
        ).first()
        assert history_entry is not None
        assert "COIN_PAYMENT" in history_entry.change_reason
    finally:
        session.close()


def test_client_admin_cannot_toggle_modules():
    """Verify Client Admin cannot toggle hardware modules (Manufacturer only)."""
    apex_token = get_token("apex_admin", "Apex@Admin2026!")
    resp = client.put(
        "/api/v1/devices/VM-000001/modules",
        json={"module_code": "RFID_ACCESS", "is_enabled": True},
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "FORBIDDEN_ACCESS"


def test_fleet_listing_strict_multi_tenant_scoping():
    """
    Verify multi-tenant fleet isolation:
    - Manufacturer sees all devices across all tenants.
    - Apex Admin sees ONLY Client Apex devices (cannot see Beta's devices).
    - Beta Admin sees ONLY Client Beta devices.
    """
    mfg_token = get_token("admin", "Admin@SecurePlatform2026!")
    apex_token = get_token("apex_admin", "Apex@Admin2026!")
    beta_token = get_token("beta_admin", "Beta@Admin2026!")

    # 1. Manufacturer list
    mfg_resp = client.get("/api/v1/devices", headers={"Authorization": f"Bearer {mfg_token}"})
    assert mfg_resp.status_code == 200
    all_dev_ids = {d["device_id"] for d in mfg_resp.json()["devices"]}
    assert "VM-000001" in all_dev_ids
    assert "VM-000099" in all_dev_ids  # Beta's machine
    assert "VM-000100" in all_dev_ids  # Newly provisioned machine

    # 2. Apex Admin list
    apex_resp = client.get("/api/v1/devices", headers={"Authorization": f"Bearer {apex_token}"})
    assert apex_resp.status_code == 200
    apex_dev_ids = {d["device_id"] for d in apex_resp.json()["devices"]}
    assert "VM-000001" in apex_dev_ids
    assert "VM-000002" in apex_dev_ids
    assert "VM-000003" in apex_dev_ids
    assert "VM-000099" not in apex_dev_ids  # CANNOT SEE BETA'S MACHINE!
    assert "VM-000100" not in apex_dev_ids  # CANNOT SEE UNASSIGNED MACHINE!

    # 3. Beta Admin list
    beta_resp = client.get("/api/v1/devices", headers={"Authorization": f"Bearer {beta_token}"})
    assert beta_resp.status_code == 200
    beta_dev_ids = {d["device_id"] for d in beta_resp.json()["devices"]}
    assert "VM-000099" in beta_dev_ids
    assert "VM-000001" not in beta_dev_ids  # CANNOT SEE APEX'S MACHINE!


def test_single_device_detail_tenant_scoping():
    """Verify single device detail endpoint rejects cross-tenant inspection with 403."""
    apex_token = get_token("apex_admin", "Apex@Admin2026!")

    # Own machine -> 200 OK
    resp_own = client.get("/api/v1/devices/VM-000001", headers={"Authorization": f"Bearer {apex_token}"})
    assert resp_own.status_code == 200
    assert resp_own.json()["device_id"] == "VM-000001"

    # Beta machine -> 403 Forbidden
    resp_foreign = client.get("/api/v1/devices/VM-000099", headers={"Authorization": f"Bearer {apex_token}"})
    assert resp_foreign.status_code == 403
    assert resp_foreign.json()["error_code"] == "TENANT_ISOLATION_VIOLATION"


def test_client_onboarding_and_listing():
    """Verify Manufacturer creates new client company and lists all clients."""
    mfg_token = get_token("admin", "Admin@SecurePlatform2026!")

    # Create new client
    new_client_payload = {
        "client_code": "CLIENT_GAMMA",
        "name": "Gamma Supermarkets Pvt Ltd",
        "contact_email": "ops@gammasuper.local",
        "contact_phone": "+91-9988776655",
        "address": "Terminal 2, Mumbai International Airport, Mumbai, India",
    }
    create_resp = client.post(
        "/api/v1/clients",
        json=new_client_payload,
        headers={"Authorization": f"Bearer {mfg_token}"},
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["client_code"] == "CLIENT_GAMMA"

    # List all clients
    list_resp = client.get("/api/v1/clients", headers={"Authorization": f"Bearer {mfg_token}"})
    assert list_resp.status_code == 200
    codes = {c["client_code"] for c in list_resp.json()["clients"]}
    assert "CLIENT_APEX" in codes
    assert "CLIENT_BETA" in codes
    assert "CLIENT_GAMMA" in codes
