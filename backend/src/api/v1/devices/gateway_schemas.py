"""
Pydantic schemas for the Device Gateway subsystem.
Covers physical device authentication, hardware handshake, heartbeats, and diagnostic logging.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class DeviceAuthRequest(BaseModel):
    """Payload sent by ESP32 during initial connection handshake."""
    device_id: str = Field(..., description="Permanent burned Device ID, e.g. VM-000001", min_length=3, max_length=32)
    chip_id: str = Field(..., description="eFuse Unique Chip ID from hardware silicon, e.g. ESP32S3-D801")
    mac_address: str = Field(..., description="Physical Wi-Fi/Ethernet MAC address, e.g. 30:AE:A4:07:00:01")
    device_token: str = Field(..., description="Secret device provisioning bearer token burned in NVS")
    firmware_version: Optional[str] = Field("v1.0.0", description="Current running firmware version")
    boot_count: Optional[int] = Field(1, description="Boot cycle counter from NVS")


class MQTTTopicMap(BaseModel):
    """Device-scoped MQTT topics configured for this node."""
    heartbeat: str
    telemetry: str
    config: str
    commands: str
    ota: str


class MQTTConnectionDetails(BaseModel):
    """MQTT connection parameters returned upon successful device authentication."""
    broker_uri: str
    port: int
    client_id: str
    topics: MQTTTopicMap


class DeviceAuthResponse(BaseModel):
    """Authentication response granting short-lived device session token and MQTT parameters."""
    session_token: str
    token_type: str = "Bearer"
    expires_in_seconds: int
    device_id: str
    client_id: Optional[str] = None
    product_type: str
    active_config_version: int
    mqtt: MQTTConnectionDetails
    server_time: datetime


class HeartbeatRequest(BaseModel):
    """Periodic health and telemetry heartbeat sent by ESP32."""
    current_firmware_version: str = Field(..., description="Running firmware version string")
    current_config_version: int = Field(..., description="Active configuration revision at edge")
    uptime_seconds: int = Field(..., description="FreeRTOS uptime counter in seconds", ge=0)
    free_heap_bytes: int = Field(..., description="Available heap memory in bytes", ge=0)
    wifi_rssi: Optional[int] = Field(None, description="Signal strength in dBm (-30 to -100)")
    ip_address: Optional[str] = Field(None, description="Current local IPv4 address")
    active_errors: Optional[List[str]] = Field(None, description="Active hardware fault codes")


class HeartbeatResponse(BaseModel):
    """Server acknowledgment of heartbeat with configuration synchronization verdict."""
    status: str = "acknowledged"
    cloud_time: datetime
    config_in_sync: bool
    active_config_version: int
    pending_commands_count: int = 0


class DeviceLogItem(BaseModel):
    """Single diagnostic or error log record from edge device."""
    log_level: str = Field("INFO", description="DEBUG, INFO, WARN, ERROR, FATAL")
    subsystem: str = Field("CORE", description="CORE, NET, CONFIG, COIN, QR, RFID, OTA")
    message: str = Field(..., description="Log message text")
    log_data: Optional[Dict[str, Any]] = None
    timestamp: Optional[datetime] = None


class DeviceLogBatchRequest(BaseModel):
    """Batch of buffered edge logs flushed to cloud."""
    logs: List[DeviceLogItem]


class DeviceLogBatchResponse(BaseModel):
    """Batch ingestion confirmation."""
    status: str = "success"
    ingested_count: int


class OfflineSweepResponse(BaseModel):
    """Response returned when sweeping stale online devices."""
    checked_at: datetime
    threshold_seconds: int
    devices_marked_offline: int
    offline_device_ids: List[str]
