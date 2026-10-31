"""
Multi-Tenant Cloud IoT Platform - FastAPI Backend Application Entry Point.
Configures middleware, exception handlers, and API v1 routing.
"""
from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
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
from src.api.v1.payments.routes import router as payments_router

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
app.include_router(payments_router, prefix="/api/v1")


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


@app.get("/pay/{device_id}", response_class=HTMLResponse, tags=["Mobile Vending Checkout"])
def mobile_pay_page(device_id: str, db: Session = Depends(get_db)):
    """
    Mobile payment checkout page for customer QR scan.
    Integrates official Razorpay Checkout SDK.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.mac_address.ilike(device_id.strip()))
    ).first()

    dev_name = device.device_id if device else device_id
    slot = device.slots[0] if (device and device.slots) else None
    product_name = slot.product.name if (slot and slot.product) else "Vending Cold Drink"
    price_paise = slot.override_price if (slot and slot.override_price is not None) else (slot.product.price if (slot and slot.product) else 1000)
    price_rupees = f"{price_paise / 100:.2f}"
    slot_num = slot.slot_number if slot else 1

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pay at {dev_name} - GTech Vending</title>
    <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
        body {{ background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%); color: #f8fafc; min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 20px; padding: 32px 24px; width: 100%; max-width: 420px; box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.5); text-align: center; }}
        .badge {{ display: inline-block; background: #0284c7; color: #fff; font-size: 12px; font-weight: 700; padding: 4px 12px; border-radius: 9999px; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 16px; }}
        h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 6px; color: #ffffff; }}
        .machine-id {{ font-size: 14px; color: #94a3b8; margin-bottom: 24px; }}
        .product-box {{ background: #0f172a; border: 1px solid #334155; border-radius: 14px; padding: 20px; margin-bottom: 24px; }}
        .product-name {{ font-size: 18px; font-weight: 600; color: #38bdf8; margin-bottom: 8px; }}
        .product-price {{ font-size: 32px; font-weight: 800; color: #22c55e; }}
        .product-price span {{ font-size: 18px; font-weight: 500; color: #94a3b8; }}
        .btn-pay {{ background: #2563eb; color: #ffffff; border: none; border-radius: 12px; width: 100%; padding: 16px; font-size: 18px; font-weight: 700; cursor: pointer; transition: all 0.2s; display: flex; align-items: center; justify-content: center; gap: 10px; box-shadow: 0 4px 14px rgba(37, 99, 235, 0.4); }}
        .btn-pay:hover {{ background: #1d4ed8; }}
        .btn-pay:active {{ transform: scale(0.98); }}
        .security-note {{ font-size: 12px; color: #64748b; margin-top: 20px; display: flex; align-items: center; justify-content: center; gap: 6px; }}
        .spinner {{ display: none; width: 24px; height: 24px; border: 3px solid rgba(255,255,255,0.3); border-radius: 50%; border-top-color: #fff; animation: spin 1s ease-in-out infinite; }}
        @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        .success-box {{ display: none; background: #064e3b; border: 1px solid #059669; border-radius: 14px; padding: 24px 16px; margin-top: 20px; }}
        .success-box h2 {{ font-size: 20px; color: #34d399; margin-bottom: 8px; }}
        .success-box p {{ font-size: 14px; color: #a7f3d0; }}
    </style>
</head>
<body>
    <div class="card" id="main-card">
        <span class="badge">⚡ Instant Zero-Touch Vending</span>
        <h1>GTech Vending Machine</h1>
        <div class="machine-id">Machine ID: <strong>{dev_name}</strong></div>

        <div class="product-box">
            <div class="product-name">{product_name}</div>
            <div class="product-price">₹{price_rupees} <span>INR</span></div>
        </div>

        <button class="btn-pay" id="pay-btn" onclick="startPayment()">
            <span id="btn-text">Pay ₹{price_rupees} with Razorpay</span>
            <div class="spinner" id="btn-spinner"></div>
        </button>

        <div class="success-box" id="success-box">
            <h2>🎉 Payment Successful!</h2>
            <p>Your item is dispensing right now at machine <strong>{dev_name}</strong>.</p>
            <p style="margin-top: 10px; font-weight: 600; color: #ffffff;">Please collect it from the tray below.</p>
        </div>

        <div class="security-note">
            🔒 Secured by <strong>Razorpay</strong> 256-bit Encryption
        </div>
    </div>

    <script>
        const deviceId = "{dev_name}";
        const slotNumber = {slot_num};

        async function startPayment() {{
            const btn = document.getElementById('pay-btn');
            const btnText = document.getElementById('btn-text');
            const spinner = document.getElementById('btn-spinner');

            btn.disabled = true;
            btnText.style.display = 'none';
            spinner.style.display = 'block';

            try {{
                const orderResp = await fetch(`/api/v1/payments/razorpay/order/create?device_id=${{deviceId}}&slot_number=${{slotNumber}}`, {{
                    method: 'POST'
                }});
                const orderData = await orderResp.json();

                const options = {{
                    key: orderData.key_id,
                    amount: orderData.amount_paise,
                    currency: orderData.currency || "INR",
                    name: "GTech Vending",
                    description: orderData.product_name,
                    order_id: orderData.razorpay_order_id,
                    handler: async function (response) {{
                        const verifyResp = await fetch('/api/v1/payments/razorpay/verify-payment', {{
                            method: 'POST',
                            headers: {{ 'Content-Type': 'application/json' }},
                            body: JSON.stringify({{
                                razorpay_order_id: response.razorpay_order_id,
                                razorpay_payment_id: response.razorpay_payment_id,
                                razorpay_signature: response.razorpay_signature
                            }})
                        }});
                        
                        btn.style.display = 'none';
                        document.getElementById('success-box').style.display = 'block';
                    }},
                    modal: {{
                        ondismiss: function() {{
                            btn.disabled = false;
                            btnText.style.display = 'inline';
                            spinner.style.display = 'none';
                        }}
                    }},
                    theme: {{ color: "#2563eb" }}
                }};

                const rzp = new Razorpay(options);
                rzp.open();
            }} catch (err) {{
                alert('Payment error: ' + err.message);
                btn.disabled = false;
                btnText.style.display = 'inline';
                spinner.style.display = 'none';
            }}
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


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
