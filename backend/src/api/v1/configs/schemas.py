"""
Configuration synchronization schemas.
Defines payloads for versioned config delivery, checksum validation,
sync acknowledgments, version auditing, and rollbacks.
"""
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class DeviceConfigPayload(BaseModel):
    """
    Complete canonical configuration payload distributed to edge ESP32 devices.
    """
    device_id: str = Field(..., description="Target device permanent ID (e.g. VM-000001)")
    product_type: str = Field(..., description="Device product family code")
    config_version: int = Field(..., description="Monotonically increasing configuration revision number")
    checksum: str = Field(..., description="SHA-256 hex digest of canonical JSON payload")
    is_synced: bool = Field(False, description="True if edge device has acknowledged this exact version")
    last_synced_at: Optional[datetime] = Field(None, description="Timestamp of last successful device ACK")
    modules: Dict[str, bool] = Field(default_factory=dict, description="Hardware feature module flags")
    module_configs: Dict[str, Any] = Field(default_factory=dict, description="Subsystem configurations")
    slots: Optional[List[Dict[str, Any]]] = Field(None, description="Vending slot pricing and coil configs")
    telemetry: Dict[str, Any] = Field(
        default_factory=lambda: {
            "heartbeat_interval_sec": 60,
            "log_level": "INFO",
            "offline_threshold_sec": 300,
        },
        description="Device telemetry settings",
    )
    settings: Dict[str, Any] = Field(default_factory=dict, description="Device-specific parameters")
    updated_at: Optional[datetime] = Field(None, description="Timestamp when this configuration was generated")


class ConfigSyncAckRequest(BaseModel):
    """
    Acknowledgment published by ESP32 node after parsing, validating, and writing config to NVS.
    """
    device_id: str = Field(..., description="Permanent device ID")
    applied_version: int = Field(..., description="The configuration version number that was applied")
    checksum: str = Field(..., description="SHA-256 checksum calculated locally by ESP32")
    status: str = Field("SUCCESS", description="Application status: SUCCESS, ERROR, or CORRUPT_PAYLOAD")
    error_message: Optional[str] = Field(None, description="Diagnostic error details if status is ERROR")
    boot_count: Optional[int] = Field(None, description="Current device boot cycle count")


class ConfigSyncAckResponse(BaseModel):
    """
    Cloud response to device config acknowledgment.
    """
    device_id: str
    status: str = Field(..., description="ACKNOWLEDGED, CHECKSUM_MISMATCH, VERSION_MISMATCH, or ERROR")
    is_synced: bool
    active_version: int
    acknowledged_at: datetime
    message: str


class ConfigurationVersionSummary(BaseModel):
    """
    Audit record of a historical configuration revision.
    """
    id: str
    device_id: str
    version_number: int
    checksum: str
    change_reason: Optional[str] = None
    created_by_user_id: Optional[str] = None
    created_at: datetime
    config_payload: Dict[str, Any]


class ConfigUpdateRequest(BaseModel):
    """
    Payload for updating device configuration settings, triggering a version bump.
    """
    modules: Optional[Dict[str, bool]] = Field(None, description="Update module enablement flags")
    module_configs: Optional[Dict[str, Any]] = Field(None, description="Update module parameters")
    slots: Optional[List[Dict[str, Any]]] = Field(None, description="Update vending machine slot prices")
    telemetry: Optional[Dict[str, Any]] = Field(None, description="Update telemetry timing")
    settings: Optional[Dict[str, Any]] = Field(None, description="Update generic device parameters")
    change_reason: str = Field("Manual configuration update", description="Reason for configuration change")


class ConfigRollbackRequest(BaseModel):
    """
    Payload for rolling back to a previous configuration version.
    """
    target_version: int = Field(..., ge=1, description="Historical version number to restore")
    change_reason: Optional[str] = Field(None, description="Reason for the rollback")


class ConfigDiffResponse(BaseModel):
    """
    Diff analysis between two configuration versions or cloud vs edge.
    """
    device_id: str
    base_version: int
    target_version: int
    has_drift: bool
    differences: Dict[str, Any]
