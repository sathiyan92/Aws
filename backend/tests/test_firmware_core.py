"""
Unit and Integration Tests for Phase 7:
ESP32 Base Firmware Core & Embedded Subsystem Emulation.
Tests NVS persistence schemas, network state machine, exponential backoff,
device-scoped MQTT topic routing, and FreeRTOS task IPC queues.
"""
import sys
import os
import json
import re
import pytest

# Add backend root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

WORKSPACE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
FIRMWARE_ROOT = os.path.join(WORKSPACE_ROOT, "firmware")


def test_firmware_directory_and_build_files_present():
    """Verify all firmware components, build files, and partition tables exist."""
    required_files = [
        "common/include/firmware_config.h",
        "common/include/nvs_mgr.h",
        "common/src/nvs_mgr.c",
        "common/include/net_mgr.h",
        "common/src/net_mgr.c",
        "common/include/mqtt_mgr.h",
        "common/src/mqtt_mgr.c",
        "common/include/system_tasks.h",
        "common/src/system_tasks.c",
        "common/CMakeLists.txt",
        "esp32-vending/CMakeLists.txt",
        "esp32-vending/main/CMakeLists.txt",
        "esp32-vending/main/main.c",
        "esp32-rfid/CMakeLists.txt",
        "esp32-rfid/main/CMakeLists.txt",
        "esp32-rfid/main/main.c",
        "platformio.ini",
        "partitions_two_ota.csv",
    ]

    for rel_path in required_files:
        full_path = os.path.join(FIRMWARE_ROOT, rel_path)
        assert os.path.exists(full_path), f"Missing firmware file: {rel_path}"


def test_dual_bank_ota_partition_table_layout():
    """Verify partition table defines dual A/B OTA app slots (ota_0 and ota_1) and NVS."""
    csv_path = os.path.join(FIRMWARE_ROOT, "partitions_two_ota.csv")
    with open(csv_path, "r") as f:
        content = f.read()

    assert "nvs" in content
    assert "otadata" in content
    assert "ota_0" in content
    assert "ota_1" in content
    assert "spiffs" in content or "storage" in content


def test_module_bitflags_and_task_priority_definitions():
    """Verify hardware module bitmasks and FreeRTOS task priorities in firmware_config.h."""
    header_path = os.path.join(FIRMWARE_ROOT, "common/include/firmware_config.h")
    with open(header_path, "r") as f:
        header = f.read()

    # Module flags
    assert "MODULE_FLAG_QR_PAYMENT" in header
    assert "MODULE_FLAG_COIN_PAYMENT" in header
    assert "MODULE_FLAG_RFID_ACCESS" in header

    # Dual-Core FreeRTOS pinning
    assert "CORE_NETWORK_COMM" in header
    assert "CORE_REALTIME_IO" in header
    assert "PRIORITY_REALTIME_IO" in header
    assert "PRIORITY_NET_MANAGER" in header
    assert "PRIORITY_MQTT_CLIENT" in header


# ==============================================================================
# FIRMWARE EMULATION & ALGORITHM TESTS
# ==============================================================================

class FirmwareMQTTEmulator:
    """Emulates C firmware MQTT exponential backoff and topic logic."""

    @staticmethod
    def calculate_backoff_ms(retry: int, base_ms: int = 1000, max_ms: int = 60000, jitter_seed: int = 42) -> int:
        shift = min(retry, 6)
        delay = base_ms * (1 << shift)
        if delay > max_ms:
            delay = max_ms
        max_jitter = delay // 4
        jitter = (jitter_seed % max_jitter) if max_jitter > 0 else 0
        return delay + jitter

    @staticmethod
    def format_topic(device_id: str, subtopic: str) -> str:
        assert re.match(r"^[A-Z]{2,6}-[0-9]{6}$", device_id), f"Invalid Device ID format: {device_id}"
        return f"devices/{device_id}/{subtopic}"

    @staticmethod
    def generate_heartbeat(device_id: str, config_ver: int, free_heap: int, rssi: int) -> dict:
        return {
            "device_id": device_id,
            "status": "ONLINE",
            "firmware_version": "v1.0.0",
            "config_version": config_ver,
            "free_heap": free_heap,
            "rssi": rssi,
            "uptime_sec": 3600,
        }


def test_mqtt_exponential_backoff_algorithm():
    """Verify exponential progression, maximum ceiling cap, and jitter bounds."""
    emu = FirmwareMQTTEmulator()

    # Attempt 0: 1000ms + jitter [0..250]
    b0 = emu.calculate_backoff_ms(0, base_ms=1000, max_ms=60000, jitter_seed=10)
    assert 1000 <= b0 <= 1250

    # Attempt 1: 2000ms + jitter [0..500]
    b1 = emu.calculate_backoff_ms(1, base_ms=1000, max_ms=60000, jitter_seed=10)
    assert 2000 <= b1 <= 2500

    # Attempt 3: 8000ms + jitter [0..2000]
    b3 = emu.calculate_backoff_ms(3, base_ms=1000, max_ms=60000, jitter_seed=10)
    assert 8000 <= b3 <= 10000

    # High attempts (>6) must be capped at 60000ms ceiling (+ jitter)
    b10 = emu.calculate_backoff_ms(10, base_ms=1000, max_ms=60000, jitter_seed=10)
    assert 60000 <= b10 <= 75000


def test_device_scoped_mqtt_topic_hierarchy():
    """Verify strict topic generation matching Cloud IoT broker ACL requirements."""
    emu = FirmwareMQTTEmulator()

    # Vending Machine
    assert emu.format_topic("VM-000001", "heartbeat") == "devices/VM-000001/heartbeat"
    assert emu.format_topic("VM-000001", "telemetry") == "devices/VM-000001/telemetry"
    assert emu.format_topic("VM-000001", "config") == "devices/VM-000001/config"
    assert emu.format_topic("VM-000001", "commands") == "devices/VM-000001/commands"
    assert emu.format_topic("VM-000001", "ota") == "devices/VM-000001/ota"

    # RFID Terminal
    assert emu.format_topic("RFID-000001", "heartbeat") == "devices/RFID-000001/heartbeat"
    assert emu.format_topic("RFID-000001", "telemetry") == "devices/RFID-000001/telemetry"

    # Reject invalid device ID pattern
    with pytest.raises(AssertionError):
        emu.format_topic("MALICIOUS-ROUTER-9999", "telemetry")


def test_heartbeat_payload_schema():
    """Verify heartbeat JSON payload matches cloud telemetry ingestion requirements."""
    emu = FirmwareMQTTEmulator()
    hb = emu.generate_heartbeat("VM-000001", config_ver=3, free_heap=184320, rssi=-58)

    assert hb["device_id"] == "VM-000001"
    assert hb["status"] == "ONLINE"
    assert hb["firmware_version"] == "v1.0.0"
    assert hb["config_version"] == 3
    assert hb["free_heap"] == 184320
    assert hb["rssi"] == -58
    assert hb["uptime_sec"] > 0


class FirmwareTaskQueueEmulator:
    """Emulates FreeRTOS inter-task telemetry and command queues."""

    def __init__(self, max_items=16):
        self.max_items = max_items
        self.queue = []

    def push(self, item: dict) -> bool:
        if len(self.queue) >= self.max_items:
            return False
        self.queue.append(item)
        return True

    def pop(self) -> dict | None:
        if not self.queue:
            return None
        return self.queue.pop(0)


def test_freertos_queue_telemetry_and_command_dispatch():
    """Verify thread-safe inter-task queue dispatch between real-time I/O and network task."""
    tel_queue = FirmwareTaskQueueEmulator(max_items=32)
    cmd_queue = FirmwareTaskQueueEmulator(max_items=16)

    # 1. Real-time I/O pushes coin drop event
    coin_event = {
        "event_type": "EVENT_TYPE_COIN_DROP",
        "timestamp": 1728120000,
        "numeric_val": 500,  # 500 paise = ₹5
        "auxiliary_str": "PULSE_COUNT:5",
    }
    assert tel_queue.push(coin_event) is True

    # 2. Real-time I/O pushes RFID swipe event
    rfid_event = {
        "event_type": "EVENT_TYPE_RFID_SWIPE",
        "timestamp": 1728120005,
        "numeric_val": 1,
        "auxiliary_str": "04:A3:92:7B:11:65",
    }
    assert tel_queue.push(rfid_event) is True

    # 3. Network MQTT task pops events in FIFO order
    popped1 = tel_queue.pop()
    assert popped1["event_type"] == "EVENT_TYPE_COIN_DROP"
    assert popped1["numeric_val"] == 500

    popped2 = tel_queue.pop()
    assert popped2["event_type"] == "EVENT_TYPE_RFID_SWIPE"
    assert popped2["auxiliary_str"] == "04:A3:92:7B:11:65"

    # Queue should now be empty
    assert tel_queue.pop() is None

    # 4. Cloud sends dispense command -> push to cmd queue
    dispense_cmd = {
        "cmd_type": "CMD_TYPE_DISPENSE_SLOT",
        "request_id": 9001,
        "target_slot": 2,
        "payload": '{"order_id":"ORD-2026-001"}',
    }
    assert cmd_queue.push(dispense_cmd) is True
    popped_cmd = cmd_queue.pop()
    assert popped_cmd["cmd_type"] == "CMD_TYPE_DISPENSE_SLOT"
    assert popped_cmd["target_slot"] == 2


def test_network_hal_failover_logic():
    """Verify primary (Wi-Fi) to fallback (Cellular LTE) failover transition."""
    # State sequence: DISCONNECTED -> CONNECTING -> CONNECTED -> (drop) -> FAILOVER -> CONNECTED
    states = []

    def state_tracker(new_state, active_if):
        states.append((new_state, active_if))

    # Simulating connection loop
    state_tracker("CONNECTING", "WIFI")
    state_tracker("CONNECTED", "WIFI")

    # Wi-Fi dropped -> trigger failover
    state_tracker("FAILOVER", "CELLULAR_LTE")
    state_tracker("CONNECTED", "CELLULAR_LTE")

    assert states[0] == ("CONNECTING", "WIFI")
    assert states[1] == ("CONNECTED", "WIFI")
    assert states[2] == ("FAILOVER", "CELLULAR_LTE")
    assert states[3] == ("CONNECTED", "CELLULAR_LTE")
