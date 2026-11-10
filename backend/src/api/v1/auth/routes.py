"""
Authentication API endpoints: login, token refresh, current user profile, and logout.
"""
from datetime import datetime, timezone
from typing import Optional
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
    ChangePasswordRequest,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _safe_audit_log(
    db: Session,
    client_id: Optional[str],
    user_id: Optional[str],
    action: str,
    entity_type: str,
    entity_id: str,
    new_state: Optional[dict] = None,
    request: Optional[Request] = None,
) -> None:
    """Safely write to AuditLog with length guards and non-fatal error handling."""
    try:
        ip_addr = str(request.client.host if (request and request.client) else "")[:45] if request else None
        ua = str(request.headers.get("user-agent", "") or "")[:250] if request else None
        db.add(AuditLog(
            client_id=client_id,
            user_id=user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            new_state=new_state,
            ip_address=ip_addr,
            user_agent=ua,
        ))
        db.commit()
    except Exception as e:
        db.rollback()
        import logging
        logging.getLogger("uvicorn.error").warning(f"Audit log write failed ({action}): {e}")


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
        email=user.email or "",
        role=user.role,
        client_id=user.client_id,
    )
    refresh_token = create_refresh_token(user_id=user.id)

    # Log successful authentication in Audit Log (non-blocking)
    _safe_audit_log(
        db=db,
        client_id=user.client_id,
        user_id=user.id,
        action="USER_LOGIN_SUCCESS",
        entity_type="USER",
        entity_id=user.id,
        new_state={"role": user.role, "client_id": user.client_id},
        request=request,
    )

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
        email=user.email or "",
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
    _safe_audit_log(
        db=db,
        client_id=current_user.client_id,
        user_id=current_user.id,
        action="USER_LOGOUT",
        entity_type="USER",
        entity_id=current_user.id,
        request=request,
    )

    return MessageResponse(message="Successfully logged out")


@router.post("/change-password", response_model=MessageResponse)
def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Securely change password and/or username. Supports both:
    1. Authenticated user (with JWT Bearer token)
    2. Direct change from login screen (providing username_or_email + current_password)
    """
    from src.core.security.hashing import verify_password, hash_password
    from src.core.exceptions.errors import BadRequestException, NotFoundException

    user = None
    # 1. Check Bearer token if supplied
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token and token != "null" and token != "undefined":
            try:
                from src.core.security.tokens import decode_token
                decoded = decode_token(token)
                user_id = decoded.get("sub")
                if user_id:
                    user = db.query(User).filter(User.id == user_id).first()
            except Exception:
                pass

    # 2. If no valid Bearer token, look up by username or email
    if not user:
        if not payload.username_or_email:
            raise BadRequestException("Please enter your current username or email address.")
        ident = payload.username_or_email.strip()
        user = db.query(User).filter((User.username == ident) | (User.email == ident)).first()
        if not user:
            raise NotFoundException(f"Account '{ident}' was not found.")

    if not verify_password(payload.current_password, user.password_hash):
        raise BadRequestException("Current password does not match.")

    changes = []

    # Update Username if requested
    if payload.new_username and payload.new_username.strip():
        new_u = payload.new_username.strip()
        if new_u != user.username:
            existing = db.query(User).filter(User.username == new_u, User.id != user.id).first()
            if existing:
                raise BadRequestException(f"Username '{new_u}' is already taken by another account.")
            old_u = user.username
            user.username = new_u
            changes.append(f"username to '{new_u}'")

    # Update Email if requested
    if payload.new_email and payload.new_email.strip():
        new_e = payload.new_email.strip()
        if new_e != user.email:
            existing_e = db.query(User).filter(User.email == new_e, User.id != user.id).first()
            if existing_e:
                raise BadRequestException(f"Email '{new_e}' is already registered to another account.")
            user.email = new_e
            changes.append(f"email to '{new_e}'")

    # Update Password if requested
    if payload.new_password and payload.new_password.strip():
        user.password_hash = hash_password(payload.new_password.strip())
        changes.append("password")

    if not changes:
        raise BadRequestException("No new credentials provided. Please enter a new username or password.")

    db.commit()

    _safe_audit_log(
        db=db,
        client_id=user.client_id,
        user_id=user.id,
        action="USER_CREDENTIALS_CHANGED",
        entity_type="USER",
        entity_id=user.id,
        new_state={"role": user.role, "username": user.username, "updated": changes},
        request=request,
    )
    change_desc = " and ".join(changes)
    return MessageResponse(message=f"Successfully updated {change_desc} for account '{user.username}'!")
