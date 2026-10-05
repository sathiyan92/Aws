"""
Unit and Integration Tests for Phase 10:
Vending Product Catalog & Slot Management Engine.
Tests catalog CRUD, physical dispensing slot configuration, live stock tracking,
multi-tenant isolation, and the Price Update Engine (updating catalog price
triggers automatic configuration version bumps, SHA-256 checksum updates,
and MQTT sync events without firmware compilation).
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
from src.db.models.device import Device
from src.db.models.vending import Product, MachineSlot
from src.db.models.config import DeviceConfig, ConfigurationVersion
from src.services.config_service import get_latest_mqtt_config_message

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_vending_database():
    """Ensure database has fresh schema and seed data for vending tests."""
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
    """Apex Vending Solutions Admin Token (CLIENT_ADMIN)."""
    return get_token("apex_admin", "Apex@Admin2026!")


@pytest.fixture
def metro_admin_token() -> str:
    """Metro Retail Networks Admin Token (CLIENT_ADMIN)."""
    return get_token("metro_admin", "Metro@Retail2026!")


@pytest.fixture
def superadmin_token() -> str:
    """Manufacturer Super-Admin Token."""
    return get_token("superadmin", "SuperAdmin@Apex2026!")


# ==============================================================================
# 1. PRODUCT CATALOG CRUD TESTS
# ==============================================================================

def test_list_client_products(apex_admin_token):
    """
    Verify client admin can list all catalog products belonging to their organization.
    Seed data provides: BEV-WATER-500, BEV-COKE-300, SNK-CHIPS-50.
    """
    resp = client.get(
        "/api/v1/vending/products",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp.status_code == 200
    products = resp.json()

    codes = [p["product_code"] for p in products]
    assert "BEV-WATER-500" in codes
    assert "BEV-COKE-300" in codes
    assert "SNK-CHIPS-50" in codes

    coke = next(p for p in products if p["product_code"] == "BEV-COKE-300")
    assert coke["price"] == 4000
    assert coke["price_rupees"] == 40.0


def test_create_new_product(apex_admin_token):
    """
    Verify client admin can create a new catalog product.
    """
    payload = {
        "product_code": "BEV-SPRITE-300",
        "name": "Sprite 300ml Can",
        "price": 4000,
        "description": "Crisp lemon-lime flavored soft drink",
        "is_active": True,
    }

    resp = client.post(
        "/api/v1/vending/products",
        json=payload,
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp.status_code == 201, f"Product creation failed: {resp.text}"
    data = resp.json()

    assert data["product_code"] == "BEV-SPRITE-300"
    assert data["name"] == "Sprite 300ml Can"
    assert data["price"] == 4000
    assert data["price_rupees"] == 40.0
    assert data["is_active"] is True


def test_create_duplicate_product_code_rejected(apex_admin_token):
    """
    Attempting to register a product with duplicate product_code in the same tenant must fail with 400.
    """
    payload = {
        "product_code": "BEV-COKE-300",  # Already exists
        "name": "Coca-Cola Duplicate",
        "price": 4200,
    }

    resp = client.post(
        "/api/v1/vending/products",
        json=payload,
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp.status_code == 400
    assert "already exists" in resp.json()["message"].lower()


def test_get_single_product_detail(apex_admin_token):
    """
    Verify retrieving a single product by SKU code or UUID.
    """
    resp = client.get(
        "/api/v1/vending/products/BEV-WATER-500",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["product_code"] == "BEV-WATER-500"
    assert data["price"] == 2000
    assert data["price_rupees"] == 20.0


# ==============================================================================
# 2. PRICE UPDATE ENGINE TESTS (NO FIRMWARE RECOMPILATION)
# ==============================================================================

def test_product_price_update_propagates_to_vending_fleet(apex_admin_token):
    """
    PRICE UPDATE ENGINE CORE REQUIREMENT:
    When a product price changes (e.g. ₹40.00 -> ₹45.00):
    1. Product price updates in database.
    2. All vending machines with slots assigned to this product (VM-000001, VM-000002, VM-000003)
       automatically have their configuration version bumped.
    3. New SHA-256 checksums are calculated over the updated canonical slot prices.
    4. is_synced is set to False (pending edge sync).
    5. Immutable ConfigurationVersion records are archived.
    6. MQTT update is published to devices/{device_id}/config.
    7. No firmware compilation or OTA flashing required.
    """
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        v1_initial = vm1.current_config_version
    finally:
        session.close()

    # Update Coke price from 4000 paise (₹40) to 4500 paise (₹45)
    update_payload = {
        "price": 4500,
        "description": "Premium chilled Coca-Cola 300ml",
    }

    put_resp = client.put(
        "/api/v1/vending/products/BEV-COKE-300",
        json=update_payload,
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert put_resp.status_code == 200
    prod_data = put_resp.json()
    assert prod_data["price"] == 4500
    assert prod_data["price_rupees"] == 45.0

    # Verify VM-000001 configuration was automatically updated and bumped
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1.current_config_version == v1_initial + 1
        assert vm1.config.is_synced is False

        # Verify active configuration payload holds the new price for slot 2
        payload = vm1.config.config_payload
        assert "slots" in payload
        slot2 = next(s for s in payload["slots"] if s["product"] == "BEV-COKE-300" or s["slot"] == 2)
        assert slot2["price"] == 4500

        # Verify immutable ConfigurationVersion archive
        archive = session.query(ConfigurationVersion).filter_by(
            device_id=vm1.id, version_number=vm1.current_config_version
        ).first()
        assert archive is not None
        assert "price changed" in archive.change_reason.lower()
        assert archive.checksum == vm1.config.checksum
    finally:
        session.close()

    # Verify MQTT notification was dispatched for VM-000001
    mqtt_msg = get_latest_mqtt_config_message("VM-000001")
    assert mqtt_msg is not None
    assert mqtt_msg["topic"] == "devices/VM-000001/config"
    assert mqtt_msg["version"] == v1_initial + 1


# ==============================================================================
# 3. MACHINE SLOT MANAGEMENT TESTS
# ==============================================================================

def test_list_machine_slots(apex_admin_token):
    """
    Verify listing all slots configured on a vending machine.
    """
    resp = client.get(
        "/api/v1/vending/VM-000001/slots",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp.status_code == 200
    slots = resp.json()

    assert len(slots) >= 3
    s1 = next(s for s in slots if s["slot_number"] == 1)
    assert s1["slot_code"] == "SLOT-01"
    assert s1["product_code"] == "BEV-WATER-500"
    assert s1["price"] == 2000
    assert s1["price_rupees"] == 20.0
    assert s1["capacity"] == 15
    assert s1["is_active"] is True


def test_configure_single_slot(apex_admin_token):
    """
    Configure a single slot: assign Sprite product, pin 22, capacity 15, stock 12.
    Automatically increments machine configuration version and emits MQTT update.
    """
    session = SessionLocal()
    try:
        sprite = session.query(Product).filter_by(product_code="BEV-SPRITE-300").first()
        assert sprite is not None
        sprite_id = sprite.id
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        prev_version = vm1.current_config_version
    finally:
        session.close()

    slot_payload = {
        "product_id": sprite_id,
        "motor_pin": 22,
        "pulse_duration_ms": 600,
        "capacity": 15,
        "current_stock": 12,
        "is_active": True,
    }

    put_resp = client.put(
        "/api/v1/vending/VM-000001/slots/3",
        json=slot_payload,
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert put_resp.status_code == 200, f"Slot config failed: {put_resp.text}"
    slot3 = put_resp.json()

    assert slot3["slot_number"] == 3
    assert slot3["product_code"] == "BEV-SPRITE-300"
    assert slot3["motor_pin"] == 22
    assert slot3["capacity"] == 15
    assert slot3["current_stock"] == 12

    # Verify device config version bumped
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1.current_config_version == prev_version + 1
        assert vm1.config.is_synced is False
    finally:
        session.close()


def test_slot_override_price(apex_admin_token):
    """
    Setting override_price on a slot allows slot-specific pricing
    different from the catalog product price.
    """
    session = SessionLocal()
    try:
        water = session.query(Product).filter_by(product_code="BEV-WATER-500").first()
        water_id = water.id
    finally:
        session.close()

    # Slot 1 override price: ₹22.00 (2200 paise) instead of catalog ₹20.00
    slot_payload = {
        "product_id": water_id,
        "override_price": 2200,
    }

    put_resp = client.put(
        "/api/v1/vending/VM-000001/slots/1",
        json=slot_payload,
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert put_resp.status_code == 200
    slot1 = put_resp.json()

    assert slot1["override_price"] == 2200
    assert slot1["price"] == 2200
    assert slot1["price_rupees"] == 22.0


def test_bulk_configure_slots(apex_admin_token):
    """
    Batch configure multiple slots at once on a vending machine.
    Generates a single configuration version increment.
    """
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        prev_ver = vm1.current_config_version
        coke = session.query(Product).filter_by(product_code="BEV-COKE-300").first()
        water = session.query(Product).filter_by(product_code="BEV-WATER-500").first()
    finally:
        session.close()

    bulk_payload = {
        "slots": [
            {"slot_number": 1, "product_id": water.id, "motor_pin": 18, "capacity": 12, "current_stock": 10},
            {"slot_number": 2, "product_id": coke.id, "motor_pin": 19, "capacity": 12, "current_stock": 8},
        ]
    }

    post_resp = client.post(
        "/api/v1/vending/VM-000001/slots/bulk",
        json=bulk_payload,
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert post_resp.status_code == 200
    slots = post_resp.json()
    assert len(slots) >= 2

    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1.current_config_version == prev_ver + 1
    finally:
        session.close()


def test_restock_slot_inventory_does_not_bump_firmware_config(apex_admin_token):
    """
    Restocking slot inventory updates live stock levels and records audit log,
    but does NOT bump configuration version (stock levels are operational state).
    """
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        prev_ver = vm1.current_config_version
    finally:
        session.close()

    restock_payload = {
        "quantity_added": 5,
    }

    post_resp = client.post(
        "/api/v1/vending/VM-000001/slots/1/restock",
        json=restock_payload,
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert post_resp.status_code == 200
    slot1 = post_resp.json()
    assert slot1["current_stock"] >= 5

    # Ensure config version remained unchanged
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1.current_config_version == prev_ver, "Restock must not increment firmware config version"
    finally:
        session.close()


# ==============================================================================
# 4. PRODUCT DELETION SAFETY CHECKS
# ==============================================================================

def test_cannot_delete_product_assigned_to_active_slot(apex_admin_token):
    """
    Deleting a product that is currently assigned to an active dispensing slot
    must be rejected with HTTP 400 Bad Request to prevent broken machines.
    """
    resp = client.delete(
        "/api/v1/vending/products/BEV-WATER-500",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert resp.status_code == 400
    assert "actively assigned" in resp.json()["message"].lower()


def test_delete_unassigned_product_succeeds(apex_admin_token):
    """
    Creating and then deleting an unassigned product succeeds cleanly.
    """
    # 1. Create temporary product
    create_resp = client.post(
        "/api/v1/vending/products",
        json={"product_code": "TEMP-SNACK-01", "name": "Temporary Snack", "price": 1500},
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert create_resp.status_code == 201

    # 2. Delete it
    del_resp = client.delete(
        "/api/v1/vending/products/TEMP-SNACK-01",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert del_resp.status_code == 204

    # 3. Verify it is gone
    get_resp = client.get(
        "/api/v1/vending/products/TEMP-SNACK-01",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert get_resp.status_code == 404


# ==============================================================================
# 5. MULTI-TENANT ISOLATION BOUNDARIES
# ==============================================================================

def test_multi_tenant_isolation_on_products_and_slots(metro_admin_token, apex_admin_token):
    """
    STRICT TENANT ISOLATION:
    1. Metro Admin cannot view Apex's products.
    2. Metro Admin cannot edit Apex's products -> 403 Forbidden.
    3. Metro Admin cannot configure Apex's machine slots (VM-000001) -> 403 Forbidden.
    4. Apex Admin cannot configure Metro's machine slots (VM-000004) -> 403 Forbidden.
    5. Attempting to assign Metro's product to Apex's slot is rejected -> 403 Forbidden.
    """
    # 1. Metro admin queries Apex's product
    r1 = client.get(
        "/api/v1/vending/products/BEV-WATER-500",
        headers={"Authorization": f"Bearer {metro_token}" if False else f"Bearer {metro_admin_token}"},
    )
    assert r1.status_code == 403, f"Expected 403, got: {r1.status_code}"

    # 2. Metro admin updates Apex's product
    r2 = client.put(
        "/api/v1/vending/products/BEV-WATER-500",
        json={"price": 9999},
        headers={"Authorization": f"Bearer {metro_admin_token}"},
    )
    assert r2.status_code == 403

    # 3. Metro admin accesses Apex's slots
    r3 = client.get(
        "/api/v1/vending/VM-000001/slots",
        headers={"Authorization": f"Bearer {metro_admin_token}"},
    )
    assert r3.status_code == 403

    # 4. Apex admin accesses Metro's slots
    r4 = client.get(
        "/api/v1/vending/VM-000004/slots",
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r4.status_code == 403

    # 5. Metro admin creates product in their catalog
    metro_prod = client.post(
        "/api/v1/vending/products",
        json={"product_code": "METRO-TEA-200", "name": "Metro Hot Tea", "price": 1000},
        headers={"Authorization": f"Bearer {metro_admin_token}"},
    ).json()

    # Apex admin attempts to assign Metro's product to VM-000001 slot 1
    r5 = client.put(
        "/api/v1/vending/VM-000001/slots/1",
        json={"product_id": metro_prod["id"]},
        headers={"Authorization": f"Bearer {apex_admin_token}"},
    )
    assert r5.status_code == 403
