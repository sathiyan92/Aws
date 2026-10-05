"""
JWT token generation, decoding, and verification engine.
Encodes role and tenant_id claims for stateless multi-tenant authorization.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import jwt
from src.core.config.settings import settings
from src.core.exceptions.errors import NotAuthenticatedException


def create_access_token(
    user_id: str,
    username: str,
    email: str,
    role: str,
    client_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed JWT access token containing tenant and RBAC claims."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: Dict[str, Any] = {
        "sub": user_id,
        "username": username,
        "email": email,
        "role": role,
        "client_id": client_id,
        "type": "access",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(
    user_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed JWT refresh token."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload: Dict[str, Any] = {
        "sub": user_id,
        "type": "refresh",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and verify token signature and expiration."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.ALGORITHM],
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise NotAuthenticatedException("Token has expired. Please log in again.")
    except jwt.InvalidTokenError:
        raise NotAuthenticatedException("Invalid token signature or structure.")


def create_device_session_token(
    device_id: str,
    device_pk: str,
    client_id: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Generate a signed JWT session token for an authenticated ESP32 device."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(hours=24)  # 24-hour device session

    payload: Dict[str, Any] = {
        "sub": device_pk,
        "device_id": device_id,
        "client_id": client_id,
        "role": "DEVICE_CLIENT",
        "type": "device_session",
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

