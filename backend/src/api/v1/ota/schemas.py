"""
Pydantic schemas for Over-The-Air (OTA) firmware repository, deployment jobs, and edge device status reporting.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class FirmwareVersionResponse(BaseModel):
    """Firmware binary asset descriptor."""
    id: str
    version_string: str
    hardware_revision: str
    device_type_code: str
    file_size_bytes: int
    sha256_checksum: str
    binary_url: str
    changelog: Optional[str] = None
    is_deprecated: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class FirmwareListResponse(BaseModel):
    total: int
    firmware_versions: List[FirmwareVersionResponse]


class OTADeploymentResponse(BaseModel):
    """Job status for an OTA firmware push."""
    id: str
    device_id: str
    device_code: str
    firmware_version_id: str
    version_string: str
    deployment_status: str  # PENDING, DOWNLOADING, INSTALLING, SUCCESS, FAILED
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class OTADeploymentListResponse(BaseModel):
    total: int
    deployments: List[OTADeploymentResponse]


class OTAPushRequest(BaseModel):
    """Payload to trigger an OTA deployment to a specific device."""
    device_id: str = Field(..., description="Target device ID, e.g. VM-000001")
    firmware_version_id: str = Field(..., description="ID of the uploaded firmware version")


class DeviceOTACheckResponse(BaseModel):
    """Response returned to ESP32 checking for pending OTA updates."""
    has_update: bool
    deployment_id: Optional[str] = None
    version: Optional[str] = None
    binary_url: Optional[str] = None
    sha256: Optional[str] = None
    file_size_bytes: Optional[int] = None


class DeviceOTAStatusReportRequest(BaseModel):
    """Payload sent by ESP32 node to report OTA progress or completion."""
    deployment_id: str = Field(..., description="ID of the active OTA deployment job")
    status: str = Field(..., description="Status: DOWNLOADING, INSTALLING, SUCCESS, FAILED")
    error_message: Optional[str] = Field(None, description="Diagnostic error details if failed")
