"""
Authentication API endpoints: login, token refresh, current user profile, and logout.
"""
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.user import User
from src.db.models.audit import AuditLog
from src.core.config.settings import settings
from src.core.security.hashing import verify_password
from src.core.security.tokens import create_access_token, create_refresh_token, decode_token
from src.core.security.dependencies import get_current_user
from src.core.exceptions.errors import (
    NotAuthenticatedException,
    ForbiddenException,
)
from src.api.v1.auth.schemas import (
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserProfileResponse,
    MessageResponse,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """Authenticate with username/email and password to receive JWT access and refresh tokens."""
    # Lookup by username or email
    user = db.query(User).filter(
        (User.username == payload.username_or_email) | (User.email == payload.username_or_email)
    ).first()

    if not user or not verify_password(payload.password, user.password_hash):
        raise NotAuthenticatedException("Invalid credentials. Please check your username/email and password.")

    if user.status != "ACTIVE":
        raise ForbiddenException(f"Account is {user.status.lower()}. Please contact platform administrator.")

    # Generate tokens
    access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        client_id=user.client_id,
    )
    refresh_token = create_refresh_token(user_id=user.id)

    # Log successful authentication in Audit Log
    db.add(AuditLog(
        client_id=user.client_id,
        user_id=user.id,
        action="USER_LOGIN_SUCCESS",
        entity_type="USER",
        entity_id=user.id,
        new_state={"role": user.role, "client_id": user.client_id},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",
        expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserProfileResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
def refresh_token(
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
):
    """Rotate access token using a valid refresh token."""
    decoded = decode_token(payload.refresh_token)
    if decoded.get("type") != "refresh":
        raise NotAuthenticatedException("Invalid token type. Refresh token required.")

    user_id = decoded.get("sub")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotAuthenticatedException("User associated with token no longer exists")

    if user.status != "ACTIVE":
        raise ForbiddenException(f"Account is {user.status.lower()}")

    new_access_token = create_access_token(
        user_id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        client_id=user.client_id,
    )

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=payload.refresh_token,
        token_type="Bearer",
        expires_in_seconds=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        user=UserProfileResponse.model_validate(user),
    )


@router.get("/me", response_model=UserProfileResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    """Retrieve profile and tenant information for the currently authenticated user."""
    return UserProfileResponse.model_validate(current_user)


@router.post("/logout", response_model=MessageResponse)
def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Logout current user session and record in audit log."""
    db.add(AuditLog(
        client_id=current_user.client_id,
        user_id=current_user.id,
        action="USER_LOGOUT",
        entity_type="USER",
        entity_id=current_user.id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    ))
    db.commit()

    return MessageResponse(message="Successfully logged out")
