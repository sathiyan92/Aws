"""
Pydantic schemas for authentication requests, responses, and user profiles.
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Credentials payload for user login."""
    username_or_email: str = Field(..., description="Username or registered email address", min_length=3)
    password: str = Field(..., description="Plaintext password", min_length=6)


class UserProfileResponse(BaseModel):
    """User profile representation returned on auth routes."""
    id: str
    client_id: Optional[str] = None
    username: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    role: str
    status: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class TokenResponse(BaseModel):
    """Bearer token response payload."""
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in_seconds: int
    user: UserProfileResponse


class RefreshTokenRequest(BaseModel):
    """Payload to rotate access token using refresh token."""
    refresh_token: str = Field(..., description="Valid JWT refresh token")


class MessageResponse(BaseModel):
    """Generic status response."""
    message: str
    status: str = "success"


class ChangePasswordRequest(BaseModel):
    """Payload to change user password or credentials."""
    username_or_email: Optional[str] = Field(None, description="Username or email (if changing before login)")
    current_password: str = Field(..., min_length=1, description="Current password")
    new_password: Optional[str] = Field(None, min_length=6, description="New password (minimum 6 characters)")
    new_username: Optional[str] = Field(None, min_length=3, description="New username (minimum 3 characters)")
    new_email: Optional[str] = Field(None, description="New email address")
