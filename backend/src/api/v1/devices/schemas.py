"""
Pydantic schemas for Device lifecycle, hardware registration, module toggles, and fleet queries.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class DeviceModuleSchema(BaseModel):
    """Subsystem module state for a physical machine."""
    module_code: str
    is_enabled: bool
    configuration: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


class DeviceRegisterRequest(BaseModel):
    """Payload sent by manufacturer to register a newly assembled physical device."""
    device_type_code: str = Field(..., description="Device type: VENDING_MACHINE or RFID_ATTENDANCE")
    hardware_id: str = Field(..., description="Board/PCB revision, e.g. HW-ESP32S3-V1.2")
    chip_id: str = Field(..., description="Unique ESP32 eFuse chip ID")
    mac_address: str = Field(..., description="Factory MAC address: XX:XX:XX:XX:XX:XX")
    factory_serial: str = Field(..., description="Permanent physical serial label")
    client_id: Optional[str] = Field(None, description="Optional initial client tenant ID")
    initial_modules: Dict[str, bool] = Field(
        default_factory=dict,
        description="Initial module enablement map, e.g. {'QR_PAYMENT': True, 'COIN_PAYMENT': False}",
    )
    device_token: Optional[str] = Field(None, description="Optional custom secret provisioning token. If omitted, cryptographically generated.")


class DeviceAssignRequest(BaseModel):
    """Payload to assign or reassign a device to a client tenant."""
    client_id: Optional[str] = Field(..., description="Target client tenant ID, or null to unassign to inventory")


class DeviceModuleToggleRequest(BaseModel):
    """Payload to enable or disable a hardware feature module on a physical device."""
    module_code: str = Field(..., description="Module identifier, e.g. QR_PAYMENT, COIN_PAYMENT, RFID_ACCESS")
    is_enabled: bool = Field(..., description="True to enable, False to disable")
    configuration: Optional[Dict[str, Any]] = Field(None, description="Optional module configuration parameters")


class DeviceResponse(BaseModel):
    """Comprehensive device profile."""
    id: str
    device_id: str
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    device_type_code: str
    device_type_name: str
    hardware_id: str
    chip_id: str
    mac_address: str
    factory_serial: str
    status: str
    is_online: bool
    current_firmware_version: str
    current_config_version: int
    last_heartbeat_at: Optional[datetime] = None
    created_at: datetime
    modules: List[DeviceModuleSchema]
    credential_auth_type: Optional[str] = None
    provisioning_token: Optional[str] = None

    model_config = {"from_attributes": True}


class DeviceListResponse(BaseModel):
    """Paginated device listing response."""
    total: int
    devices: List[DeviceResponse]


class DeviceTypeResponse(BaseModel):
    """Product type schema descriptor."""
    id: str
    code: str
    name: str
    description: Optional[str] = None
    supported_modules: Optional[List[str]] = None

    model_config = {"from_attributes": True}


class DeviceUpdateHardwareRequest(BaseModel):
    """Payload to update physical hardware details and operational status."""
    hardware_id: Optional[str] = Field(None, description="Board/PCB revision, e.g. HW-ESP32S3-V1.2")
    chip_id: Optional[str] = Field(None, description="Unique ESP32 eFuse chip ID")
    mac_address: Optional[str] = Field(None, description="Factory MAC address: XX:XX:XX:XX:XX:XX")
    factory_serial: Optional[str] = Field(None, description="Permanent physical serial label")
    status: Optional[str] = Field(None, description="Device status: PROVISIONED, ASSIGNED, ACTIVE, MAINTENANCE, SUSPENDED, DECOMMISSIONED")
    current_firmware_version: Optional[str] = Field(None, description="Firmware version string")


class DeviceDeleteResponse(BaseModel):
    """Response returned upon device deletion."""
    status: str
    device_id: str
    message: str

