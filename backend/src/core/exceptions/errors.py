"""
Standard application exceptions and HTTP error mappings for the platform.
"""
from typing import Optional, Any
from fastapi import HTTPException, status


class PlatformException(HTTPException):
    """Base platform exception with error code and detail."""
    def __init__(self, status_code: int, detail: str, error_code: str, extra: Optional[Any] = None):
        super().__init__(status_code=status_code, detail={"error_code": error_code, "message": detail, "extra": extra})
        self.error_code = error_code


class NotAuthenticatedException(PlatformException):
    """Raised when authentication credentials are missing, invalid, or expired."""
    def __init__(self, detail: str = "Authentication credentials invalid or expired"):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="NOT_AUTHENTICATED",
        )


class ForbiddenException(PlatformException):
    """Raised when user lacks required role or permission."""
    def __init__(self, detail: str = "Insufficient permissions to perform this action"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="FORBIDDEN_ACCESS",
        )


class TenantIsolationException(PlatformException):
    """
    CRITICAL SECURITY VIOLATION:
    Raised when a tenant attempts to read or mutate another tenant's devices or data.
    """
    def __init__(self, detail: str = "Cross-tenant access strictly prohibited by isolation policy"):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="TENANT_ISOLATION_VIOLATION",
        )


class ModuleDisabledException(PlatformException):
    """
    Raised when an action requires a hardware module that is disabled on the target device.
    Enforces backend authorization so client cannot bypass UI hiding.
    """
    def __init__(self, module_code: str, device_id: str):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Module '{module_code}' is disabled on device '{device_id}'",
            error_code="MODULE_DISABLED_FOR_DEVICE",
            extra={"module_code": module_code, "device_id": device_id},
        )


class NotFoundException(PlatformException):
    """Raised when requested resource does not exist."""
    def __init__(self, resource: str, identifier: str):
        super().__init__(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{resource} '{identifier}' not found",
            error_code="RESOURCE_NOT_FOUND",
        )


class BadRequestException(PlatformException):
    """Raised on invalid client input."""
    def __init__(self, detail: str):
        super().__init__(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=detail,
            error_code="BAD_REQUEST",
        )


class ConflictException(PlatformException):
    """Raised when an operation conflicts with existing resource state."""
    def __init__(self, detail: str, error_code: str = "RESOURCE_CONFLICT", extra: Optional[Any] = None):
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail=detail,
            error_code=error_code,
            extra=extra,
        )



class DeviceAuthFailedException(PlatformException):
    """Raised when ESP32 token or signature verification fails."""
    def __init__(self, detail: str = "Device authentication failed. Invalid token or credentials."):
        super().__init__(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=detail,
            error_code="DEVICE_AUTHENTICATION_FAILED",
        )


class HardwareMismatchException(PlatformException):
    """
    CRITICAL SECURITY VIOLATION:
    Raised when device token is presented with non-matching physical MAC or eFuse Chip ID.
    Prevents cloned tokens from spoofing physical devices.
    """
    def __init__(self, detail: str = "Hardware identity mismatch. Chip ID or MAC does not match factory provisioning."):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="HARDWARE_IDENTITY_MISMATCH",
        )


class CredentialRevokedException(PlatformException):
    """Raised when device credentials have been marked revoked in the database."""
    def __init__(self, detail: str = "Device credentials have been revoked by platform administrator."):
        super().__init__(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=detail,
            error_code="CREDENTIAL_REVOKED",
        )
