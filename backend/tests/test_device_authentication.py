"""
Unit and Integration Tests for Phase 8:
Device Registration and Secure Authentication Gateway.
Tests ESP32 physical hardware handshake, eFuse/MAC verification, anti-cloning protection,
revocation enforcement, heartbeat ingestion, config drift detection, and offline device sweep.
"""
import sys
import os
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient

# Add backend root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import app
from src.db.session import SessionLocal, engine
from src.db.base import Base
from src.db.seed import seed_database
from src.db.models.device import Device, DeviceCredential
from src.db.models.telemetry import DeviceHeartbeat, DeviceLog
from src.db.models.audit import AuditLog

client = TestClient(app)

# Seeded Hardware Credentials for VM-000001
VM1_CHIP_ID = "ESP32-S3-0x3C8427F8B101"
VM1_MAC_ADDR = "3C:84:27:F8:B1:01"
VM1_TOKEN = "dev_token_VM-000001"

# Seeded Hardware Credentials for VM-000002
VM2_CHIP_ID = "ESP32-S3-0x3C8427F8B102"
VM2_MAC_ADDR = "3C:84:27:F8:B1:02"
VM2_TOKEN = "dev_token_VM-000002"


@pytest.fixture(scope="session", autouse=True)
def setup_gateway_database():
    """Ensure database is seeded with initial clients, devices, and credentials."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_database(session)
    finally:
        session.close()


def test_device_successful_handshake_and_authentication():
    """
    Verify ESP32 hardware handshake with valid token, chip ID, and MAC address.
    Should return session token and MQTT topic map.
    """
    handshake_payload = {
        "device_id": "VM-000001",
        "chip_id": VM1_CHIP_ID,
        "mac_address": VM1_MAC_ADDR,
        "device_token": VM1_TOKEN,
        "firmware_version": "v1.0.0",
        "boot_count": 3,
    }

    resp = client.post("/api/v1/device-gateway/authenticate", json=handshake_payload)
    assert resp.status_code == 200, f"Handshake failed: {resp.text}"

    data = resp.json()
    assert "session_token" in data
    assert data["token_type"] == "Bearer"
    assert data["device_id"] == "VM-000001"
    assert data["active_config_version"] >= 1
    assert data["product_type"] == "VENDING_MACHINE"

    # Verify MQTT configuration
    mqtt = data["mqtt"]
    assert mqtt["port"] == 8883
    assert mqtt["client_id"] == "VM-000001"
    assert mqtt["topics"]["heartbeat"] == "devices/VM-000001/heartbeat"
    assert mqtt["topics"]["telemetry"] == "devices/VM-000001/telemetry"
    assert mqtt["topics"]["config"] == "devices/VM-000001/config"
    assert mqtt["topics"]["commands"] == "devices/VM-000001/commands"

    # Verify database state was updated
    session = SessionLocal()
    try:
        dev = session.query(Device).filter(Device.device_id == "VM-000001").first()
        assert dev.is_online is True
        assert dev.last_heartbeat_at is not None

        # Verify audit log
        audit = session.query(AuditLog).filter(
            AuditLog.entity_id == dev.id,
            AuditLog.action == "DEVICE_AUTHENTICATED",
        ).first()
        assert audit is not None
        assert audit.new_state["chip_id"] == VM1_CHIP_ID
    finally:
        session.close()


def test_device_authentication_invalid_token_rejected():
    """Verify that an incorrect device token is rejected with HTTP 401."""
    payload = {
        "device_id": "VM-000001",
        "chip_id": VM1_CHIP_ID,
        "mac_address": VM1_MAC_ADDR,
        "device_token": "dev_token_MALICIOUS_FORGED",
    }
    resp = client.post("/api/v1/device-gateway/authenticate", json=payload)
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "DEVICE_AUTHENTICATION_FAILED"


def test_device_authentication_hardware_mismatch_rejected():
    """
    CRITICAL ANTI-CLONING SECURITY TEST:
    Verify that presenting a valid token on an unauthorized/cloned physical chip (MAC/Chip ID mismatch)
    is blocked with HTTP 403 HARDWARE_IDENTITY_MISMATCH.
    """
    payload = {
        "device_id": "VM-000001",
        "chip_id": "ESP32-ROGUE-CHIP",             # Mismatched Chip ID
        "mac_address": VM1_MAC_ADDR,
        "device_token": VM1_TOKEN,                 # Legitimate token
    }
    resp = client.post("/api/v1/device-gateway/authenticate", json=payload)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "HARDWARE_IDENTITY_MISMATCH"
    assert "does not match factory records" in resp.json()["message"]


def test_device_authentication_revoked_credential_rejected():
    """Verify that a device with revoked credentials is denied connection."""
    session = SessionLocal()
    try:
        dev = session.query(Device).filter(Device.device_id == "VM-000002").first()
        cred = session.query(DeviceCredential).filter(DeviceCredential.device_id == dev.id).first()
        cred.is_revoked = True
        session.commit()
    finally:
        session.close()

    payload = {
        "device_id": "VM-000002",
        "chip_id": VM2_CHIP_ID,
        "mac_address": VM2_MAC_ADDR,
        "device_token": VM2_TOKEN,
    }
    resp = client.post("/api/v1/device-gateway/authenticate", json=payload)
    assert resp.status_code == 403
    assert resp.json()["error_code"] == "CREDENTIAL_REVOKED"

    # Restore credential for subsequent tests
    session = SessionLocal()
    try:
        dev = session.query(Device).filter(Device.device_id == "VM-000002").first()
        cred = session.query(DeviceCredential).filter(DeviceCredential.device_id == dev.id).first()
        cred.is_revoked = False
        session.commit()
    finally:
        session.close()


def test_device_heartbeat_ingestion_and_telemetry():
    """Verify authenticated heartbeat reports telemetry and creates time-series record."""
    # 1. Authenticate to get session token
    auth_resp = client.post("/api/v1/device-gateway/authenticate", json={
        "device_id": "VM-000001",
        "chip_id": VM1_CHIP_ID,
        "mac_address": VM1_MAC_ADDR,
        "device_token": VM1_TOKEN,
    })
    assert auth_resp.status_code == 200, f"Auth failed: {auth_resp.text}"
    session_token = auth_resp.json()["session_token"]

    # 2. Report heartbeat
    hb_payload = {
        "current_firmware_version": "v1.0.0",
        "current_config_version": 1,
        "uptime_seconds": 7200,
        "free_heap_bytes": 163840,
        "wifi_rssi": -54,
        "ip_address": "192.168.1.105",
        "active_errors": [],
    }

    resp = client.post(
        "/api/v1/device-gateway/heartbeat",
        json=hb_payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "acknowledged"
    assert data["config_in_sync"] is True
    assert "cloud_time" in data

    # 3. Verify record in database
    session = SessionLocal()
    try:
        dev = session.query(Device).filter(Device.device_id == "VM-000001").first()
        hb = session.query(DeviceHeartbeat).filter(DeviceHeartbeat.device_id == dev.id).order_by(DeviceHeartbeat.recorded_at.desc()).first()
        assert hb is not None
        assert hb.uptime_seconds == 7200
        assert hb.free_heap_bytes == 163840
        assert hb.wifi_rssi == -54
    finally:
        session.close()


def test_device_heartbeat_detects_configuration_drift():
    """Verify heartbeat identifies when edge config revision lags behind cloud revision."""
    # 1. Bump device config version in cloud to v5
    session = SessionLocal()
    try:
        dev = session.query(Device).filter(Device.device_id == "VM-000001").first()
        dev.current_config_version = 5
        session.commit()
    finally:
        session.close()

    # 2. Device reports that it is still on v1
    auth_resp = client.post("/api/v1/device-gateway/authenticate", json={
        "device_id": "VM-000001",
        "chip_id": VM1_CHIP_ID,
        "mac_address": VM1_MAC_ADDR,
        "device_token": VM1_TOKEN,
    })
    session_token = auth_resp.json()["session_token"]

    resp = client.post(
        "/api/v1/device-gateway/heartbeat",
        json={
            "current_firmware_version": "v1.0.0",
            "current_config_version": 1,  # Edge is on v1, cloud is on v5
            "uptime_seconds": 300,
            "free_heap_bytes": 170000,
        },
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["config_in_sync"] is False
    assert data["active_config_version"] == 5


def test_device_diagnostic_log_batch_ingestion():
    """Verify batch ingestion of diagnostic logs from edge device."""
    auth_resp = client.post("/api/v1/device-gateway/authenticate", json={
        "device_id": "VM-000001",
        "chip_id": VM1_CHIP_ID,
        "mac_address": VM1_MAC_ADDR,
        "device_token": VM1_TOKEN,
    })
    session_token = auth_resp.json()["session_token"]

    logs_payload = {
        "logs": [
            {
                "log_level": "WARN",
                "subsystem": "COIN",
                "message": "Mechanical coin pulse debounce jitter detected on PIN 14",
                "log_data": {"raw_pulse_ms": 12},
            },
            {
                "log_level": "INFO",
                "subsystem": "NET",
                "message": "Wi-Fi link RSSI stabilized at -52 dBm",
            },
        ]
    }

    resp = client.post(
        "/api/v1/device-gateway/logs",
        json=logs_payload,
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "success"
    assert resp.json()["ingested_count"] == 2

    # Verify persisted in DB
    session = SessionLocal()
    try:
        dev = session.query(Device).filter(Device.device_id == "VM-000001").first()
        log_entry = session.query(DeviceLog).filter(
            DeviceLog.device_id == dev.id,
            DeviceLog.subsystem == "COIN",
        ).first()
        assert log_entry is not None
        assert "debounce jitter" in log_entry.message
    finally:
        session.close()


def test_offline_detection_worker_marks_stale_devices():
    """Verify that devices whose heartbeats have ceased are marked offline."""
    session = SessionLocal()
    try:
        dev = session.query(Device).filter(Device.device_id == "VM-000003").first()
        dev.is_online = True
        # Set last_heartbeat_at to 300 seconds ago
        dev.last_heartbeat_at = datetime.now(timezone.utc) - timedelta(seconds=300)
        session.commit()
    finally:
        session.close()

    # Trigger offline check with threshold of 120 seconds
    resp = client.post("/api/v1/device-gateway/offline-check?threshold_seconds=120")
    assert resp.status_code == 200
    data = resp.json()
    assert "VM-000003" in data["offline_device_ids"]
    assert data["devices_marked_offline"] >= 1

    # Verify in DB
    session = SessionLocal()
    try:
        dev = session.query(Device).filter(Device.device_id == "VM-000003").first()
        assert dev.is_online is False
    finally:
        session.close()
