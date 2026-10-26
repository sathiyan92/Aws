"""
Multi-Tenant Cloud IoT Platform - FastAPI Backend Application Entry Point.
Configures middleware, exception handlers, and API v1 routing.
"""
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
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
from fastapi.staticfiles import StaticFiles
import os
from src.api.v1.auth.routes import router as auth_router
from src.api.v1.devices.routes import router as device_router
from src.api.v1.clients.routes import router as client_router
from src.api.v1.audit.routes import router as audit_router
from src.api.v1.vending.routes import router as vending_router
from src.api.v1.rfid.routes import router as rfid_router
from src.api.v1.devices.gateway_routes import router as gateway_router
from src.api.v1.configs.routes import router as config_router
from src.api.v1.orders.routes import router as orders_router
from src.api.v1.ota.routes import router as ota_router

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


# Mount API Routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(device_router, prefix="/api/v1")
app.include_router(client_router, prefix="/api/v1")
app.include_router(audit_router, prefix="/api/v1")
app.include_router(vending_router, prefix="/api/v1")
app.include_router(rfid_router, prefix="/api/v1")
app.include_router(gateway_router, prefix="/api/v1")
app.include_router(config_router, prefix="/api/v1")
app.include_router(orders_router, prefix="/api/v1")
app.include_router(ota_router, prefix="/api/v1")


@app.on_event("startup")
def startup_init_database():
    """Ensure database tables exist and seed initial devices if database is empty."""
    from src.db.base import Base
    from src.db.session import engine, SessionLocal
    from src.db.seed import seed_database
    from src.db.models.device import Device
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        if not session.query(Device).first():
            seed_database(session)
    except Exception as e:
        print(f"[!] Startup DB init notice: {e}")
    finally:
        session.close()


@app.get("/", include_in_schema=False)
def root_redirect():
    """Redirect root domain traffic to Manufacturer Portal."""
    return RedirectResponse(url="/portal")


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
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.id == device_id)
    ).first()

    if not device:
        raise NotFoundException("Device", device_id)

    context.assert_device_access(device)

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
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN", "MANUFACTURER_SUPPORT")),
    db: Session = Depends(get_db),
):
    """
    Super-admin only endpoint returning complete fleet telemetry and distribution.
    """
    from src.db.models.device import DeviceType, DeviceModule
    from src.db.models.audit import AuditLog

    clients_count = db.query(Client).count()
    devices_count = db.query(Device).count()
    online_count = db.query(Device).filter(Device.is_online == True).count()

    # Status breakdown
    statuses = ["PROVISIONED", "ASSIGNED", "ACTIVE", "MAINTENANCE", "SUSPENDED"]
    status_map = {s: db.query(Device).filter(Device.status == s).count() for s in statuses}

    # Product family breakdown
    vending_count = db.query(Device).join(DeviceType).filter(DeviceType.code == "VENDING_MACHINE").count()
    rfid_count = db.query(Device).join(DeviceType).filter(DeviceType.code == "RFID_ATTENDANCE").count()

    # Module breakdown
    qr_count = db.query(DeviceModule).filter(DeviceModule.module_code == "QR_PAYMENT", DeviceModule.is_enabled == True).count()
    coin_count = db.query(DeviceModule).filter(DeviceModule.module_code == "COIN_PAYMENT", DeviceModule.is_enabled == True).count()
    rfid_mod_count = db.query(DeviceModule).filter(DeviceModule.module_code == "RFID_ACCESS", DeviceModule.is_enabled == True).count()

    # Recent activity
    recent_audits = db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(10).all()

    return {
        "clients_count": clients_count,
        "devices_count": devices_count,
        "online_devices_count": online_count,
        "offline_devices_count": devices_count - online_count,
        "status_breakdown": status_map,
        "product_type_breakdown": {
            "VENDING_MACHINE": vending_count,
            "RFID_ATTENDANCE": rfid_count,
        },
        "module_breakdown": {
            "QR_PAYMENT": qr_count,
            "COIN_PAYMENT": coin_count,
            "RFID_ACCESS": rfid_mod_count,
        },
        "recent_audits": [
            {
                "id": a.id,
                "action": a.action,
                "entity_type": a.entity_type,
                "entity_id": a.entity_id,
                "created_at": a.created_at,
            }
            for a in recent_audits
        ],
        "access": "UNRESTRICTED_GLOBAL",
    }


# Mount static directory for Manufacturer Portal UI if directory exists
portal_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/manufacturer-portal"))
if os.path.exists(portal_dir):
    app.mount("/portal", StaticFiles(directory=portal_dir, html=True), name="manufacturer_portal")

# Mount static directory for Client Tenant Portal UI if directory exists
client_portal_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../frontend/client-portal"))
if os.path.exists(client_portal_dir):
    app.mount("/client-portal", StaticFiles(directory=client_portal_dir, html=True), name="client_portal")
