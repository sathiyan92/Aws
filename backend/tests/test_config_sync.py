"""
Unit and Integration Tests for Phase 9:
Cloud Configuration Synchronization.
Tests canonical payload serialization, cryptographic SHA-256 checksums,
configuration version incrementing, out-of-sync drift detection via heartbeat,
edge device configuration fetch, acknowledgment validation, checksum tamper protection,
immutable revision history, rollback engine, and multi-tenant security boundaries.
"""
import sys
import os
import json
import hashlib
from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient

# Add backend root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import app
from src.db.session import SessionLocal, engine
from src.db.base import Base
from src.db.seed import seed_database
from src.db.models.device import Device
from src.db.models.config import DeviceConfig, ConfigurationVersion
from src.db.models.telemetry import DeviceLog
from src.services.config_service import (
    compute_canonical_checksum,
    build_device_composite_payload,
    get_latest_mqtt_config_message,
)

client = TestClient(app)

# Seeded Hardware Credentials for VM-000001
VM1_CHIP_ID = "ESP32-S3-0x3C8427F8B101"
VM1_MAC_ADDR = "3C:84:27:F8:B1:01"
VM1_TOKEN = "dev_token_VM-000001"


@pytest.fixture(scope="module", autouse=True)
def setup_config_database():
    """Ensure database has fresh schema and seed data for config sync tests."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_database(session)
    finally:
        session.close()


def get_user_token(username: str, password: str) -> str:
    """Helper to authenticate and retrieve access token for a user."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": username, "password": password},
    )
    assert resp.status_code == 200, f"Login failed for {username}: {resp.text}"
    return resp.json()["access_token"]


def get_device_session_token(device_id: str, chip_id: str, mac_addr: str, token: str) -> str:
    """Helper to execute hardware handshake and get device session JWT."""
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
    assert resp.status_code == 200, f"Device handshake failed: {resp.text}"
    return resp.json()["session_token"]


# ==============================================================================
# 1. CANONICAL SERIALIZATION & CHECKSUM DETERMINISM TESTS
# ==============================================================================

def test_canonical_checksum_generation_determinism():
    """
    Verify canonical JSON produces identical SHA-256 hashes regardless
    of dictionary key insertion order, whitespace, or nested structures.
    """
    dict_a = {
        "device_id": "VM-000001",
        "config_version": 1,
        "modules": {"QR_PAYMENT": True, "COIN_PAYMENT": False},
        "slots": [{"slot": 1, "price": 4000}, {"slot": 2, "price": 2000}],
    }

    # Different insertion order
    dict_b = {
        "slots": [{"price": 4000, "slot": 1}, {"price": 2000, "slot": 2}],
        "modules": {"COIN_PAYMENT": False, "QR_PAYMENT": True},
        "config_version": 1,
        "device_id": "VM-000001",
    }

    raw_a, checksum_a = compute_canonical_checksum(dict_a)
    raw_b, checksum_b = compute_canonical_checksum(dict_b)

    assert checksum_a == checksum_b, "Checksum must be strictly deterministic across key ordering"
    assert len(checksum_a) == 64, "Checksum must be 64-char hex string (SHA-256)"

    # Altering single value must alter checksum
    dict_c = dict(dict_a)
    dict_c["config_version"] = 2
    _, checksum_c = compute_canonical_checksum(dict_c)
    assert checksum_c != checksum_a, "Mutating config_version must yield different checksum"


def test_composite_config_payload_generation():
    """
    Verify build_device_composite_payload correctly extracts slots, modules,
    and telemetry parameters for both Vending and RFID product types.
    """
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1 is not None
        payload_vm = build_device_composite_payload(vm1)

        assert payload_vm["device_id"] == "VM-000001"
        assert payload_vm["product_type"] == "VENDING_MACHINE"
        assert "modules" in payload_vm
        assert "slots" in payload_vm
        assert len(payload_vm["slots"]) >= 1

        rfid1 = session.query(Device).filter_by(device_id="RFID-000001").first()
        assert rfid1 is not None
        payload_rfid = build_device_composite_payload(rfid1)

        assert payload_rfid["device_id"] == "RFID-000001"
        assert payload_rfid["product_type"] == "RFID_ATTENDANCE"
        assert "modules" in payload_rfid
        assert payload_rfid["modules"].get("RFID_ACCESS") is True
    finally:
        session.close()


# ==============================================================================
# 2. CLOUD CONFIGURATION VERSION INCREMENTOR & MQTT BROADCAST TESTS
# ==============================================================================

def test_cloud_config_update_bumps_version_and_marks_unsynced():
    """
    Updating configuration settings on a device:
    1. Bumps active_version (v1 -> v2).
    2. Recalculates SHA-256 checksum.
    3. Sets is_synced = False (pending edge ACK).
    4. Appends immutable ConfigurationVersion record.
    5. Dispatches to simulated MQTT topic devices/{device_id}/config.
    """
    apex_token = get_user_token("apex_admin", "Apex@Admin2026!")

    update_payload = {
        "telemetry": {"heartbeat_interval_sec": 30, "log_level": "DEBUG"},
        "slots": [
            {"slot": 1, "code": "SLOT-01", "product": "BEV-WATER-500", "price": 2500, "pin": 18, "capacity": 15, "stock": 10, "is_active": True},
            {"slot": 2, "code": "SLOT-02", "product": "BEV-COKE-300", "price": 4500, "pin": 19, "capacity": 15, "stock": 8, "is_active": True},
        ],
        "change_reason": "Summer beverage price adjustment",
    }

    patch_resp = client.patch(
        "/api/v1/devices/VM-000001/config",
        json=update_payload,
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert patch_resp.status_code == 200, f"Config update failed: {patch_resp.text}"
    data = patch_resp.json()

    assert data["config_version"] == 2
    assert data["is_synced"] is False
    assert len(data["checksum"]) == 64
    assert data["telemetry"]["heartbeat_interval_sec"] == 30
    assert data["slots"][0]["price"] == 2500

    # Verify immutable version archive in DB
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1.current_config_version == 2
        assert vm1.config.is_synced is False
        assert vm1.config.checksum == data["checksum"]

        v2_archive = session.query(ConfigurationVersion).filter_by(
            device_id=vm1.id, version_number=2
        ).first()
        assert v2_archive is not None
        assert v2_archive.change_reason == "Summer beverage price adjustment"
        assert v2_archive.checksum == data["checksum"]
    finally:
        session.close()

    # Verify MQTT config event was published to devices/VM-000001/config
    mqtt_msg = get_latest_mqtt_config_message("VM-000001")
    assert mqtt_msg is not None
    assert mqtt_msg["topic"] == "devices/VM-000001/config"
    assert mqtt_msg["version"] == 2
    assert mqtt_msg["checksum"] == data["checksum"]


# ==============================================================================
# 3. OUT-OF-SYNC DETECTION VIA HEARTBEAT TELEMETRY
# ==============================================================================

def test_heartbeat_detects_out_of_sync_drift():
    """
    When edge sends heartbeat reporting stale version (v1),
    cloud detects config drift and responds config_in_sync: False.
    """
    dev_session = get_device_session_token("VM-000001", VM1_CHIP_ID, VM1_MAC_ADDR, VM1_TOKEN)

    # Edge sends heartbeat with v1 (lagging behind cloud's active v2)
    hb_resp = client.post(
        "/api/v1/device-gateway/heartbeat",
        json={
            "current_firmware_version": "v1.0.0",
            "current_config_version": 1,
            "uptime_seconds": 1200,
            "free_heap_bytes": 185000,
            "wifi_rssi": -62,
            "ip_address": "192.168.1.101",
        },
        headers={"Authorization": f"Bearer {dev_session}"},
    )
    assert hb_resp.status_code == 200
    hb_data = hb_resp.json()

    assert hb_data["config_in_sync"] is False, "Cloud must signal out-of-sync drift"
    assert hb_data["active_config_version"] == 2


# ==============================================================================
# 4. EDGE CONFIGURATION FETCH & ACKNOWLEDGMENT SYNC
# ==============================================================================

def test_edge_device_fetches_active_config_and_acknowledges():
    """
    Upon detecting drift:
    1. Edge node fetches active config from gateway.
    2. Edge validates version and checksum.
    3. Edge sends ACK with applied_version=2 and matching checksum.
    4. Cloud marks device is_synced=True and updates last_synced_at.
    5. Subsequent heartbeat reports config_in_sync=True.
    """
    dev_session = get_device_session_token("VM-000001", VM1_CHIP_ID, VM1_MAC_ADDR, VM1_TOKEN)

    # 1. Edge fetches config
    cfg_resp = client.get(
        "/api/v1/device-gateway/config",
        headers={"Authorization": f"Bearer {dev_session}"},
    )
    assert cfg_resp.status_code == 200
    active_cfg = cfg_resp.json()

    assert active_cfg["config_version"] == 2
    assert active_cfg["is_synced"] is False
    assert len(active_cfg["checksum"]) == 64

    # 2. Edge posts successful ACK
    ack_resp = client.post(
        "/api/v1/device-gateway/config/ack",
        json={
            "device_id": "VM-000001",
            "applied_version": 2,
            "checksum": active_cfg["checksum"],
            "status": "SUCCESS",
            "boot_count": 2,
        },
        headers={"Authorization": f"Bearer {dev_session}"},
    )
    assert ack_resp.status_code == 200
    ack_data = ack_resp.json()

    assert ack_data["status"] == "ACKNOWLEDGED"
    assert ack_data["is_synced"] is True
    assert ack_data["active_version"] == 2

    # Verify DB state
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1.config.is_synced is True
        assert vm1.config.last_synced_at is not None

        # Verify diagnostic log was added
        log_entry = session.query(DeviceLog).filter_by(
            device_id=vm1.id, subsystem="CONFIG"
        ).order_by(DeviceLog.recorded_at.desc()).first()
        assert log_entry is not None
        assert "v2 successfully synchronized" in log_entry.message
    finally:
        session.close()

    # 3. Subsequent heartbeat should now report in-sync
    hb_resp = client.post(
        "/api/v1/device-gateway/heartbeat",
        json={
            "current_firmware_version": "v1.0.0",
            "current_config_version": 2,
            "uptime_seconds": 1260,
            "free_heap_bytes": 184500,
            "wifi_rssi": -61,
            "ip_address": "192.168.1.101",
        },
        headers={"Authorization": f"Bearer {dev_session}"},
    )
    assert hb_resp.status_code == 200
    assert hb_resp.json()["config_in_sync"] is True


# ==============================================================================
# 5. ERROR CASES & CHECKSUM TAMPER PROTECTION
# ==============================================================================

def test_tampered_or_corrupt_checksum_ack_rejected():
    """
    If edge attempts to ACK with tampered or corrupt checksum,
    cloud rejects with CHECKSUM_MISMATCH and keeps is_synced=False.
    """
    dev_session = get_device_session_token("VM-000001", VM1_CHIP_ID, VM1_MAC_ADDR, VM1_TOKEN)
    bogus_checksum = "deadbeef" * 8

    ack_resp = client.post(
        "/api/v1/device-gateway/config/ack",
        json={
            "device_id": "VM-000001",
            "applied_version": 2,
            "checksum": bogus_checksum,
            "status": "SUCCESS",
        },
        headers={"Authorization": f"Bearer {dev_session}"},
    )
    assert ack_resp.status_code == 200
    ack_data = ack_resp.json()

    assert ack_data["status"] == "CHECKSUM_MISMATCH"
    assert ack_data["is_synced"] is False
    assert "checksum" in ack_data["message"].lower()

    # Verify device config is marked unsynced
    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1.config.is_synced is False
    finally:
        session.close()


def test_stale_version_ack_rejected():
    """
    If edge attempts to ACK a version that doesn't match cloud active version,
    cloud rejects with VERSION_MISMATCH and keeps is_synced=False.
    """
    dev_session = get_device_session_token("VM-000001", VM1_CHIP_ID, VM1_MAC_ADDR, VM1_TOKEN)

    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        correct_checksum = vm1.config.checksum
    finally:
        session.close()

    ack_resp = client.post(
        "/api/v1/device-gateway/config/ack",
        json={
            "device_id": "VM-000001",
            "applied_version": 99,  # Incorrect future version
            "checksum": correct_checksum,
            "status": "SUCCESS",
        },
        headers={"Authorization": f"Bearer {dev_session}"},
    )
    assert ack_resp.status_code == 200
    ack_data = ack_resp.json()

    assert ack_data["status"] == "VERSION_MISMATCH"
    assert ack_data["is_synced"] is False


def test_edge_hardware_error_reported_in_ack():
    """
    If edge reports flash/NVS error in ACK, cloud marks is_synced=False
    and logs the error event into device_logs.
    """
    dev_session = get_device_session_token("VM-000001", VM1_CHIP_ID, VM1_MAC_ADDR, VM1_TOKEN)

    session = SessionLocal()
    try:
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        valid_checksum = vm1.config.checksum
    finally:
        session.close()

    ack_resp = client.post(
        "/api/v1/device-gateway/config/ack",
        json={
            "device_id": "VM-000001",
            "applied_version": 2,
            "checksum": valid_checksum,
            "status": "ERROR",
            "error_message": "NVS_STATUS_ERR_WRITE_FAILED: flash block corrupted",
        },
        headers={"Authorization": f"Bearer {dev_session}"},
    )
    assert ack_resp.status_code == 200
    ack_data = ack_resp.json()

    assert ack_data["status"] == "ERROR"
    assert ack_data["is_synced"] is False


# ==============================================================================
# 6. CONFIGURATION ROLLBACK & AUDIT TRAIL TESTS
# ==============================================================================

def test_configuration_rollback_creates_forward_revision():
    """
    Rolling back to v1:
    1. Creates v3 holding v1 payload settings.
    2. Keeps append-only history immutable.
    3. Sets is_synced=False.
    """
    apex_token = get_user_token("apex_admin", "Apex@Admin2026!")

    rb_resp = client.post(
        "/api/v1/devices/VM-000001/config/rollback",
        json={"target_version": 1, "change_reason": "Emergency rollback to baseline pricing"},
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert rb_resp.status_code == 200, f"Rollback failed: {rb_resp.text}"
    rb_data = rb_resp.json()

    assert rb_data["config_version"] == 3, "Rollback creates forward revision v3"
    assert rb_data["is_synced"] is False
    assert len(rb_data["checksum"]) == 64

    # Verify history contains v1, v2, and v3
    hist_resp = client.get(
        "/api/v1/devices/VM-000001/config/history",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert hist_resp.status_code == 200
    history = hist_resp.json()

    versions = [h["version_number"] for h in history]
    assert 3 in versions
    assert 2 in versions
    assert 1 in versions
    assert history[0]["version_number"] == 3
    assert "Emergency rollback" in history[0]["change_reason"]


def test_configuration_diff_endpoint():
    """
    Verify /devices/{device_id}/config/diff returns accurate key-level diffs
    between two configuration revisions.
    """
    apex_token = get_user_token("apex_admin", "Apex@Admin2026!")

    diff_resp = client.get(
        "/api/v1/devices/VM-000001/config/diff?base_version=1&target_version=2",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert diff_resp.status_code == 200
    diff_data = diff_resp.json()

    assert diff_data["base_version"] == 1
    assert diff_data["target_version"] == 2
    assert diff_data["has_drift"] is True
    assert "differences" in diff_data


# ==============================================================================
# 7. MULTI-TENANT ISOLATION BOUNDARY ENFORCEMENT
# ==============================================================================

def test_multi_tenant_isolation_blocks_cross_tenant_config_access():
    """
    STRICT TENANT ISOLATION:
    1. Metro Admin cannot read VM-000001 (Apex's device) config -> 403 Forbidden.
    2. Metro Admin cannot update VM-000001 config -> 403 Forbidden.
    3. Metro Admin cannot view VM-000001 config history -> 403 Forbidden.
    4. Apex Admin cannot read VM-000004 (Metro's device) config -> 403 Forbidden.
    """
    metro_token = get_user_token("metro_admin", "Metro@Retail2026!")
    apex_token = get_user_token("apex_admin", "Apex@Admin2026!")

    # 1. Metro admin queries Apex device config
    r1 = client.get(
        "/api/v1/devices/VM-000001/config",
        headers={"Authorization": f"Bearer {metro_token}"},
    )
    assert r1.status_code == 403, f"Cross-tenant read must be forbidden, got: {r1.status_code}"

    # 2. Metro admin updates Apex device config
    r2 = client.patch(
        "/api/v1/devices/VM-000001/config",
        json={"change_reason": "Malicious cross-tenant write"},
        headers={"Authorization": f"Bearer {metro_token}"},
    )
    assert r2.status_code == 403, f"Cross-tenant write must be forbidden, got: {r2.status_code}"

    # 3. Metro admin views Apex device history
    r3 = client.get(
        "/api/v1/devices/VM-000001/config/history",
        headers={"Authorization": f"Bearer {metro_token}"},
    )
    assert r3.status_code == 403, f"Cross-tenant history must be forbidden, got: {r3.status_code}"

    # 4. Apex admin queries Metro device config
    r4 = client.get(
        "/api/v1/devices/VM-000004/config",
        headers={"Authorization": f"Bearer {apex_token}"},
    )
    assert r4.status_code == 403, f"Cross-tenant read must be forbidden, got: {r4.status_code}"
