"""
FastAPI security dependencies: authentication, tenant context, and RBAC guards.
Enforces multi-tenant data boundaries and prevents cross-tenant data leakage.
"""
from typing import Optional, List, Callable
from fastapi import Depends, Header, Path
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.user import User
from src.db.models.device import Device, DeviceModule
from src.core.security.tokens import decode_token
from src.core.exceptions.errors import (
    NotAuthenticatedException,
    ForbiddenException,
    TenantIsolationException,
    ModuleDisabledException,
    NotFoundException,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate Bearer token and retrieve active User entity."""
    if not token:
        raise NotAuthenticatedException("Authorization header with Bearer token is required")

    payload = decode_token(token)
    if payload.get("type") != "access":
        raise NotAuthenticatedException("Invalid token type. Access token required.")

    user_id = payload.get("sub")
    if not user_id:
        raise NotAuthenticatedException("Token payload missing user identifier")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise NotAuthenticatedException("User associated with token no longer exists")

    if user.status != "ACTIVE":
        raise ForbiddenException(f"User account is {user.status.lower()}")

    return user


class TenantContext:
    """
    Encapsulates the tenant scope of the authenticated request.
    Enforces strict physical and logical boundary rules between clients.
    """
    def __init__(self, user: User):
        self.user = user
        self.user_id = user.id
        self.role = user.role
        self.client_id = user.client_id
        # Manufacturer users have NULL client_id and MANUFACTURER role
        self.is_manufacturer = user.client_id is None and user.role.startswith("MANUFACTURER")

    def has_role(self, *allowed_roles: str) -> bool:
        """Check if user has one of the allowed roles."""
        return self.role in allowed_roles

    def assert_tenant_access(self, target_client_id: Optional[str]) -> None:
        """
        Enforce tenant isolation.
        Manufacturer admins can inspect any tenant.
        Client users are strictly restricted to their own client_id.
        """
        if self.is_manufacturer:
            return

        if not target_client_id or self.client_id != target_client_id:
            raise TenantIsolationException(
                f"Access denied: Cannot access resources of client '{target_client_id}' from tenant '{self.client_id}'"
            )

    def assert_device_access(self, device: Device) -> None:
        """Enforce that client users can only access devices assigned directly to them."""
        if self.is_manufacturer:
            return

        if device.client_id != self.client_id:
            raise TenantIsolationException(
                f"Access denied: Device '{device.device_id}' does not belong to your organization"
            )


def get_tenant_context(
    current_user: User = Depends(get_current_user),
) -> TenantContext:
    """Dependency yielding verified TenantContext for the requesting user."""
    return TenantContext(current_user)


def require_roles(*allowed_roles: str) -> Callable[[TenantContext], TenantContext]:
    """Dependency factory enforcing that the user has at least one of the specified roles."""
    def role_checker(context: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if not context.has_role(*allowed_roles):
            raise ForbiddenException(
                f"Action requires one of roles: {list(allowed_roles)}. Your role is '{context.role}'."
            )
        return context

    return role_checker


def require_device_module(module_code: str) -> Callable:
    """
    Dependency factory enforcing that a hardware module is enabled on the target device.
    Rejects unauthorized requests at backend level, backing up dynamic UI hiding.
    """
    def module_checker(
        device_id: str = Path(..., description="Device ID or UUID"),
        context: TenantContext = Depends(get_tenant_context),
        db: Session = Depends(get_db),
    ) -> Device:
        # Lookup device by permanent device_id or primary key id
        device = db.query(Device).filter(
            (Device.device_id == device_id) | (Device.id == device_id)
        ).first()

        if not device:
            raise NotFoundException("Device", device_id)

        # Enforce tenant ownership of device
        context.assert_device_access(device)

        # Check module enablement
        mod = db.query(DeviceModule).filter(
            DeviceModule.device_id == device.id,
            DeviceModule.module_code == module_code,
            DeviceModule.is_enabled == True,
        ).first()

        if not mod:
            raise ModuleDisabledException(module_code, device.device_id)

        return device

    return module_checker
