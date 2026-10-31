"""
Order API Router.
Provides transaction-based dynamic QR payment intent endpoints:
initiation, real-time polling, cancellation, and tenant-scoped order history.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.core.security.dependencies import (
    TenantContext,
    get_tenant_context,
    require_roles,
)
from src.api.v1.orders.schemas import (
    OrderInitiateRequest,
    OrderInitiateResponse,
    OrderDetailResponse,
    OrderCancelResponse,
)
from src.services.order_service import (
    initiate_order,
    get_order_detail,
    cancel_order,
    list_orders,
    mark_order_paid,
    mark_order_dispensed,
)

router = APIRouter(prefix="/orders", tags=["Dynamic QR Orders & Payments"])


@router.post("/initiate", response_model=OrderInitiateResponse, status_code=status.HTTP_201_CREATED)
def initiate_purchase_order(
    payload: OrderInitiateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    [Public / Edge Kiosk Endpoint]
    Initiate a dynamic, transaction-based QR purchase intent for a selected vending machine slot.
    - Validates machine status and stock availability.
    - Enforces QR_PAYMENT module policy.
    - Dynamically resolves configured slot price without firmware recompilation.
    - Generates dynamic UPI payload with unique order nonce and 180s countdown timer.
    """
    client_ip = request.client.host if request and request.client else None
    return initiate_order(db=db, payload=payload, client_ip=client_ip)


@router.get("/{order_id}", response_model=OrderDetailResponse)
def get_order_status(
    order_id: str,
    db: Session = Depends(get_db),
):
    """
    [Polling Endpoint]
    Retrieve real-time payment and dispense status for an initiated order.
    Automatically checks and marks expired orders if countdown reaches 0.
    """
    return get_order_detail(db=db, order_id_or_number=order_id)


@router.post("/{order_id}/cancel", response_model=OrderCancelResponse)
def cancel_pending_order(
    order_id: str,
    reason: Optional[str] = Query("USER_CANCELLED", description="Cancellation reason"),
    db: Session = Depends(get_db),
):
    """
    Cancel an active pending dynamic QR order before payment completion.
    """
    return cancel_order(db=db, order_id_or_number=order_id, reason=reason)


@router.post("/{order_id}/mark-paid", response_model=OrderDetailResponse)
def mark_payment_success(
    order_id: str,
    gateway_txn_id: Optional[str] = Query(None, description="Optional bank / gateway transaction ref"),
    db: Session = Depends(get_db),
):
    """
    [Payment Webhook / Kiosk Simulator Endpoint]
    Transitions a pending dynamic QR order to PAID upon receiving payment confirmation.
    Signals the ESP32 to immediately activate vending motors.
    """
    return mark_order_paid(db=db, order_id_or_number=order_id, gateway_txn_id=gateway_txn_id)


@router.post("/{order_id}/dispensed", response_model=OrderDetailResponse)
def mark_dispense_complete(
    order_id: str,
    dispense_token: Optional[str] = Query(None, description="One-time dispense authorization token"),
    db: Session = Depends(get_db),
):
    """
    [Edge Hardware Callback Endpoint]
    Called by ESP32 once physical product dispense is confirmed (e.g., motor cycle complete).
    Validates single-use dispense_token, transitions order to DISPENSED,
    and decrements machine slot inventory.
    """
    return mark_order_dispensed(db=db, order_id_or_number=order_id, dispense_token=dispense_token)


@router.get("", response_model=List[OrderDetailResponse])
def get_orders_list(
    device_id: Optional[str] = Query(None, description="Filter by device ID"),
    status: Optional[str] = Query(None, description="Filter by order status (e.g. PENDING, PAID, DISPENSED)"),
    limit: int = Query(50, ge=1, le=200),
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    [Tenant Scoped]
    List purchase orders for the client tenant's fleet.
    Enforces strict multi-tenant boundaries.
    """
    effective_client_id = None if context.is_manufacturer else context.client_id
    return list_orders(
        db=db,
        client_id=effective_client_id,
        device_id=device_id,
        status_filter=status,
        limit=limit,
    )


@router.get("/pending-dispense/{device_id}")
def check_pending_dispense(
    device_id: str,
    x_device_token: Optional[str] = Header(None, alias="X-Device-Token"),
    db: Session = Depends(get_db),
):
    """
    [Edge Hardware Polling Endpoint - Buttonless Zero-Touch Vending]
    The ESP32 periodically queries this endpoint to check if an incoming
    Razorpay payment has matched a product price and authorized motor dispense.
    """
    from src.services.order_service import get_pending_dispense_for_device
    return get_pending_dispense_for_device(db=db, device_id=device_id, device_token=x_device_token)


@router.get("/qr-bitmap/{device_id}")
def get_device_qr_bitmap(
    device_id: str,
    format: str = Query("bmp", regex="^(bmp|png)$"),
    size: int = Query(200, ge=100, le=480),
    db: Session = Depends(get_db),
):
    """
    [Edge Hardware Bitmap Endpoint]
    Generates and streams a clean monochrome BMP or PNG image for the machine's TFT LCD.
    Encodes the exact direct UPI payload, never image_url.
    Suitable for ESP32 ILI9488 TFT direct rendering without local QR math.
    """
    import io
    import qrcode
    from src.services.order_service import get_device_qr_config

    cfg = get_device_qr_config(db=db, device_id=device_id)
    upi_payload = cfg.get("qr_payload") or f"upi://pay?pa={cfg.get('razorpay_upi_vpa')}&pn=IoT%20Vending&am={cfg.get('amount_rupees'):.2f}&cu=INR&tn={device_id}"

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=max(2, size // 35),
        border=2,
    )
    qr.add_data(upi_payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("1")
    img = img.resize((size, size))

    buf = io.BytesIO()
    if format == "png":
        img.save(buf, format="PNG")
        media_type = "image/png"
    else:
        img.save(buf, format="BMP")
        media_type = "image/bmp"

    return Response(content=buf.getvalue(), media_type=media_type)


@router.get("/razorpay-webhook")
@router.get("/razorpay-webhook/")
@router.head("/razorpay-webhook")
@router.head("/razorpay-webhook/")
def handle_razorpay_webhook_get():
    """Health check ping for Razorpay Webhook validation."""
    return {"status": "OK", "gateway": "RAZORPAY", "service": "orders-webhook-receiver"}


@router.post("/razorpay-webhook")
@router.post("/razorpay-webhook/")
async def handle_razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    [Razorpay Webhook Handler - Legacy & Order-specific Alias]
    Forwards to central Razorpay webhook processing with raw body HMAC verification
    and idempotency protection.
    """
    from src.services.razorpay_service import process_webhook_event
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature") or request.headers.get("x-razorpay-signature")
    return process_webhook_event(
        db=db,
        raw_body=raw_body,
        signature=signature,
        enforce_signature=True,
    )


@router.get("/qr-config/{device_id}")
def get_qr_configuration(
    device_id: str,
    db: Session = Depends(get_db),
):
    """
    [Edge & Dashboard Endpoint]
    Fetch active QR code, VPA, and price configuration for a machine.
    Used by ESP32 to detect remote QR code changes in real-time.
    """
    from src.services.order_service import get_device_qr_config
    return get_device_qr_config(db=db, device_id=device_id)


@router.put("/qr-config/{device_id}")
def update_qr_configuration(
    device_id: str,
    payload: dict,
    db: Session = Depends(get_db),
):
    """
    [Vendor / Manufacturer Portal Endpoint]
    Allows vendor or manufacturer to change the QR code, UPI VPA, price, or product name online.
    Increments config version so the ESP32 immediately redraws its screen.
    """
    from src.services.order_service import update_device_qr_config
    return update_device_qr_config(db=db, device_id=device_id, payload_data=payload)


