"""
Pydantic schemas for RFID Vending Machine subsystem.
"""
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class RFIDCardCreate(BaseModel):
    card_uid: str = Field(..., description="RFID Tag UID in Hex, e.g. A1B2C3D4")
    username: str = Field(..., description="Name of the cardholder")
    department: Optional[str] = None
    device_id: Optional[str] = None
    client_id: Optional[str] = None
    daily_limit: int = Field(default=1, description="Daily vend limit (0 or -1 for unlimited)")
    is_active: bool = True
    notes: Optional[str] = None


class RFIDCardUpdate(BaseModel):
    username: Optional[str] = None
    department: Optional[str] = None
    device_id: Optional[str] = None
    daily_limit: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


class RFIDCardResponse(BaseModel):
    id: str
    client_id: str
    device_id: Optional[str] = None
    device_code: Optional[str] = None
    card_uid: str
    username: str
    department: Optional[str] = None
    daily_limit: int
    used_today: int
    last_vended_at: Optional[datetime] = None
    is_active: bool
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RFIDCardBatchGenerate(BaseModel):
    device_id: Optional[str] = None
    client_id: Optional[str] = None
    prefix: str = Field(default="USER-", description="Prefix for username")
    uid_prefix: Optional[str] = Field(default="RFID-", description="Prefix for card UID")
    start_num: int = Field(default=1, ge=1)
    end_num: int = Field(default=1000, le=5000)
    pad_digits: int = Field(default=4, ge=1, le=8)
    department: Optional[str] = "Batch Generated"
    daily_limit: int = 1


class RFIDVerifyTapRequest(BaseModel):
    device_id: str
    card_uid: str
    offline_buffer: bool = False
    pulse_ms: Optional[int] = 1500


class RFIDVerifyTapResponse(BaseModel):
    authorized: bool
    status: str
    card_uid: str
    username: Optional[str] = None
    department: Optional[str] = None
    daily_limit: int = 1
    used_today: int = 0
    dispense_pulse_ms: int = 1500
    message: str


class RFIDOfflineSyncItem(BaseModel):
    card_uid: str
    timestamp: Optional[datetime] = None
    dispense_ms: int = 1500


class RFIDOfflineSyncRequest(BaseModel):
    device_id: str
    logs: List[RFIDOfflineSyncItem]


class RFIDLogItem(BaseModel):
    id: str
    timestamp: datetime
    client_id: str
    vendor_name: Optional[str] = None
    device_id: str
    device_code: Optional[str] = None
    card_uid: str
    username: str
    department: Optional[str] = None
    status: str
    pulse_duration_ms: int
    notes: Optional[str] = None

    model_config = {"from_attributes": True}


class EnrollModeToggle(BaseModel):
    enabled: bool

