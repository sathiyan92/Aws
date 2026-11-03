"""
Pydantic schemas for Client (Tenant) management.
"""
from typing import Optional, List
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class ClientCreateRequest(BaseModel):
    """Payload to create a new client tenant organization with optional vendor login & machine assignment."""
    client_code: str = Field(..., description="Unique alphanumeric tenant code (e.g. METRO_RETAIL)", min_length=3, max_length=32)
    name: str = Field(..., description="Company or legal entity name", min_length=2, max_length=255)
    contact_email: str = Field(..., description="Primary administrative contact email", min_length=5, max_length=255)
    contact_phone: Optional[str] = Field(None, description="Support or emergency contact phone")
    address: Optional[str] = Field(None, description="Physical installation or corporate address")
    admin_username: Optional[str] = Field(None, description="Vendor login username")
    admin_password: Optional[str] = Field(None, description="Vendor login password")
    assign_device_id: Optional[str] = Field(None, description="Initial machine ID to assign to this vendor")


class ClientUpdateRequest(BaseModel):
    """Payload to update client tenant details."""
    name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    status: Optional[str] = None
    address: Optional[str] = None


class ClientResponse(BaseModel):
    """Client tenant summary representation."""
    id: str
    client_code: str
    name: str
    contact_email: str
    contact_phone: Optional[str] = None
    status: str
    address: Optional[str] = None
    created_at: datetime
    device_count: int = 0
    active_device_count: int = 0

    model_config = {"from_attributes": True}


class ClientListResponse(BaseModel):
    """List of client organizations."""
    total: int
    clients: List[ClientResponse]


class ClientUserCreateRequest(BaseModel):
    """Payload to create or reset credentials for a client vendor user."""
    username: str = Field(..., min_length=3, max_length=64)
    email: EmailStr = Field(...)
    password: str = Field(..., min_length=6)
    full_name: Optional[str] = None
