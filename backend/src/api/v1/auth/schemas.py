"""
Pydantic schemas for authentication requests, responses, and user profiles.
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Credentials payload for user login."""
    username_or_email: str = Field(..., description="Username or registered email address", min_length=3)
    password: str = Field(..., description="Plaintext password", min_length=6)


class UserProfileResponse(BaseModel):
    """User profile representation returned on auth routes."""
    id: str
    client_id: Optional[str] = None
    username: str
    email: str
    full_name: str
    role: str
    status: str
    created_at: datetime

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
