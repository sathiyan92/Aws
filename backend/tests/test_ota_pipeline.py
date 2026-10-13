"""
Unit and Integration Tests for OTA Firmware Management & Deployment Pipeline.
Tests firmware binary upload, catalog listing, targeting specific ESP32 devices,
device OTA polling, binary download streaming, and device status reporting.
"""
import sys
import os
import io
import pytest
from fastapi.testclient import TestClient

# Add backend root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.main import app
from src.db.session import SessionLocal
from src.db.models.device import Device
from src.db.models.firmware import FirmwareVersion, OTADeployment

client = TestClient(app)


def get_mfg_token() -> str:
    """Helper to authenticate as Manufacturer Admin."""
    resp = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": "Admin@SecurePlatform2026!"},
    )
    assert resp.status_code == 200
    return resp.json()["access_token"]


def test_ota_full_lifecycle_targeting_specific_esp32():
    """
    Test uploading a .bin firmware binary from portal, targeting a particular ESP32 (VM-000001),
    polling update on the ESP32, streaming the binary, and reporting SUCCESS.
    """
    token = get_mfg_token()
    headers = {"Authorization": f"Bearer {token}"}
    session = SessionLocal()

    try:
        # 1. Ensure target device exists
        target_dev = session.query(Device).filter_by(device_id="VM-000001").first()
        assert target_dev is not None

        # 2. Upload dummy .bin firmware artifact targeting VM-000001
        mock_bin_content = b"\xE9\x08\x02\x3F\xAA\xBB\xCC\xDD ESP32 COMPILED FIRMWARE TEST BINARY"
        files = {
            "file": ("esp32_firmware_v2_0_0.bin", io.BytesIO(mock_bin_content), "application/octet-stream")
        }
        data = {
            "version_string": "v2.0.0",
            "device_type_code": "VENDING_MACHINE",
            "hardware_revision": "HW-ESP32S3-V1.2",
            "changelog": "Critical stability fix and coin pulse optimization",
            "target_device_id": "VM-000001",
        }

        upload_resp = client.post("/api/v1/ota/firmware/upload", headers=headers, files=files, data=data)
        assert upload_resp.status_code == 200, upload_resp.text
        fw_data = upload_resp.json()
        assert fw_data["version_string"] == "v2.0.0"
        assert fw_data["file_size_bytes"] == len(mock_bin_content)
        assert "sha256_checksum" in fw_data
        assert fw_data["binary_url"] is not None

        # 3. Verify firmware listed in catalog
        list_resp = client.get("/api/v1/ota/firmware", headers=headers)
        assert list_resp.status_code == 200
        versions = [f["version_string"] for f in list_resp.json()["firmware_versions"]]
        assert "v2.0.0" in versions

        # 4. Simulate ESP32 checking for pending OTA update
        check_resp = client.get("/api/v1/ota/check/VM-000001")
        assert check_resp.status_code == 200
        check_data = check_resp.json()
        assert check_data["has_update"] is True
        assert check_data["version"] == "v2.0.0"
        assert check_data["file_size_bytes"] == len(mock_bin_content)
        deployment_id = check_data["deployment_id"]
        assert deployment_id is not None

        # 5. Simulate ESP32 downloading binary stream
        binary_url = check_data["binary_url"]
        filename = binary_url.split("/")[-1]
        dl_resp = client.get(f"/api/v1/ota/binaries/{filename}")
        assert dl_resp.status_code == 200
        assert dl_resp.content == mock_bin_content

        # 6. Simulate ESP32 reporting status DOWNLOADING
        status_resp1 = client.post(
            "/api/v1/ota/status",
            json={"deployment_id": deployment_id, "status": "DOWNLOADING"}
        )
        assert status_resp1.status_code == 200
        assert status_resp1.json()["deployment_status"] == "DOWNLOADING"

        # 7. Simulate ESP32 successfully flashing and reporting SUCCESS
        status_resp2 = client.post(
            "/api/v1/ota/status",
            json={"deployment_id": deployment_id, "status": "SUCCESS"}
        )
        assert status_resp2.status_code == 200
        assert status_resp2.json()["deployment_status"] == "SUCCESS"

        # 8. Verify the device entity's current_firmware_version has been updated
        session.refresh(target_dev)
        assert target_dev.current_firmware_version == "v2.0.0"
    finally:
        session.close()


def test_ota_push_to_particular_device_api():
    """
    Test using POST /api/v1/ota/deploy to push an already registered firmware version
    to a specific device.
    """
    token = get_mfg_token()
    headers = {"Authorization": f"Bearer {token}"}
    session = SessionLocal()

    try:
        fw = session.query(FirmwareVersion).first()
        assert fw is not None, "Need at least one firmware version"

        target_dev = session.query(Device).filter_by(device_id="VM-000002").first()
        if not target_dev:
            target_dev = session.query(Device).first()

        deploy_payload = {
            "device_id": target_dev.device_id,
            "firmware_version_id": fw.id,
        }

        resp = client.post("/api/v1/ota/deploy", headers=headers, json=deploy_payload)
        assert resp.status_code == 200
        deploy_data = resp.json()
        assert deploy_data["deployment_status"] == "PENDING"
        assert deploy_data["device_code"] == target_dev.device_id

        # Check that device now sees the update
        check_resp = client.get(f"/api/v1/ota/check/{target_dev.device_id}")
        assert check_resp.status_code == 200
        assert check_resp.json()["has_update"] is True
        assert check_resp.json()["version"] == fw.version_string
    finally:
        session.close()
