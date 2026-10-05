"""
Multi-Tenant Cloud IoT Platform - FastAPI Backend Application Entry Point.
Configures middleware, exception handlers, and API v1 routing.
"""
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from src.core.config.settings import settings
from src.core.exceptions.errors import PlatformException, NotFoundException
from src.core.security.dependencies import (
    TenantContext,
    get_tenant_context,
    require_roles,
    require_device_module,
)
from src.db.session import get_db
from src.db.models.device import Device
from src.db.models.client import Client
from src.api.v1.auth.routes import router as auth_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    description="Multi-Tenant Cloud IoT Platform for Commercial Vending Machines and RFID Attendance Systems.",
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception handler for platform-specific security & business exceptions
@app.exception_handler(PlatformException)
async def platform_exception_handler(request: Request, exc: PlatformException):
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail,
    )


# Mount Authentication Router
app.include_router(auth_router, prefix="/api/v1")


@app.get("/health", tags=["Health"])
def health_check():
    """System health check endpoint."""
    return {
        "status": "healthy",
        "service": settings.PROJECT_NAME,
        "version": settings.PROJECT_VERSION,
        "environment": settings.ENVIRONMENT,
    }


# ------------------------------------------------------------------------------
# Demonstration & Verification Endpoints for Multi-Tenant Isolation & Module Guards
# ------------------------------------------------------------------------------

@app.get("/api/v1/tenants/{target_client_id}/devices", tags=["Multi-Tenancy Demo"])
def list_tenant_devices(
    target_client_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Retrieve devices belonging to a client tenant.
    STRICT SECURITY RULE:
    A client user can ONLY query their own client_id. Cross-tenant access is rejected with 403 Forbidden.
    Manufacturer admins can inspect any client tenant.
    """
    # Enforce tenant boundary
    context.assert_tenant_access(target_client_id)

    devices = db.query(Device).filter(Device.client_id == target_client_id).all()
    return {
        "tenant_id": target_client_id,
        "requested_by_user": context.user.username,
        "user_role": context.role,
        "devices_count": len(devices),
        "devices": [
            {
                "id": d.id,
                "device_id": d.device_id,
                "status": d.status,
                "is_online": d.is_online,
                "hardware_id": d.hardware_id,
                "firmware_version": d.current_firmware_version,
                "config_version": d.current_config_version,
            }
            for d in devices
        ],
    }


@app.get("/api/v1/devices/{device_id}/modules/{module_code}/access", tags=["Module Guard Demo"])
def access_device_module_feature(
    device_id: str,
    module_code: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Demonstrates backend policy enforcement for hardware feature modules.
    Rejects requests with 403 MODULE_DISABLED if the module is disabled on the target machine.
    """
    # Lookup device
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()

    if not device:
        raise NotFoundException("Device", device_id)

    # Enforce tenant ownership of device
    context.assert_device_access(device)

    # Check module
    from src.db.models.device import DeviceModule
    mod = db.query(DeviceModule).filter(
        DeviceModule.device_id == device.id,
        DeviceModule.module_code == module_code,
        DeviceModule.is_enabled == True,
    ).first()

    if not mod:
        from src.core.exceptions.errors import ModuleDisabledException
        raise ModuleDisabledException(module_code, device.device_id)

    return {
        "status": "granted",
        "device_id": device.device_id,
        "module_code": module_code,
        "is_enabled": True,
        "message": f"Access granted to module '{module_code}' for machine '{device.device_id}'",
    }


@app.get("/api/v1/manufacturer/platform-stats", tags=["Manufacturer Admin Only"])
def get_platform_statistics(
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Super-admin only endpoint.
    Protected by RBAC guard: requires MANUFACTURER_ADMIN role.
    """
    clients_count = db.query(Client).count()
    devices_count = db.query(Device).count()
    return {
        "clients_count": clients_count,
        "devices_count": devices_count,
        "caller_role": context.role,
        "access": "UNRESTRICTED_GLOBAL",
    }
