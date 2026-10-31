"""
Razorpay Payments API Router.
Provides:
- Webhook receiver (POST /api/v1/payments/razorpay/webhook)
- Dynamic and Static QR creation (POST /api/v1/payments/razorpay/qr/create)
- Public client configuration (GET /api/v1/payments/razorpay/config)
- Webhook audit log inspection (GET /api/v1/payments/webhook-events)
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Header, Request, status, HTTPException
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.core.config.settings import settings
from src.core.exceptions.errors import NotFoundException
from src.db.models.vending import RazorpayQRCode, WebhookEvent
from src.api.v1.payments.schemas import (
    RazorpayQRCreateRequest,
    RazorpayQRResponse,
    RazorpayConfigResponse,
    RazorpayVerifyPaymentRequest,
    RazorpayVerifyPaymentResponse,
)
from src.services.razorpay_service import (
    process_webhook_event,
    create_razorpay_qr,
    verify_payment_signature,
)

router = APIRouter(prefix="/payments", tags=["Razorpay Payments & Webhooks"])


@router.post("/razorpay/webhook", status_code=status.HTTP_200_OK)
async def razorpay_webhook_endpoint(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    [Razorpay Webhook Handler]
    Receives raw-body HTTP POST notifications from Razorpay:
    - payment.captured
    - qr_code.credited
    - payment.authorized
    
    Verifies X-Razorpay-Signature using HMAC SHA-256 against raw body bytes.
    Protects against duplicate delivery using the WebhookEvent database table.
    Authorizes dispense on target machine slot.
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature") or request.headers.get("x-razorpay-signature")

    return process_webhook_event(
        db=db,
        raw_body=raw_body,
        signature=signature,
        enforce_signature=True,
    )


@router.get("/razorpay/config", response_model=RazorpayConfigResponse)
def get_razorpay_public_config():
    """
    [Public Config Endpoint]
    Returns Razorpay public key ID and mode status for frontend/kiosk displays.
    Key secret and webhook secret are NEVER returned.
    """
    return RazorpayConfigResponse(
        key_id=settings.RAZORPAY_KEY_ID,
        test_mode=settings.RAZORPAY_TEST_MODE,
        currency=settings.RAZORPAY_CURRENCY,
    )


@router.post("/razorpay/qr/create", response_model=RazorpayQRResponse, status_code=status.HTTP_201_CREATED)
def create_qr_endpoint(
    payload: RazorpayQRCreateRequest,
    db: Session = Depends(get_db),
):
    """
    [QR Code Creation Endpoint]
    Generate a dynamic (single_use) or static (multiple_use) UPI QR code for a vending machine slot.
    Uses Razorpay QR API when live test keys are configured, or generates standard UPI QR payload in test mode.
    """
    return create_razorpay_qr(
        db=db,
        device_id=payload.device_id,
        slot_number=payload.slot_number,
        amount_rupees=payload.amount_rupees,
        usage=payload.usage or "single_use",
        name_override=payload.name,
    )


@router.get("/razorpay/qr/{qr_id}", response_model=RazorpayQRResponse)
def get_qr_endpoint(
    qr_id: str,
    db: Session = Depends(get_db),
):
    """
    Retrieve stored Razorpay QR Code details and current status.
    """
    qr = db.query(RazorpayQRCode).filter(
        (RazorpayQRCode.razorpay_qr_id == qr_id) | (RazorpayQRCode.id == qr_id)
    ).first()
    if not qr:
        raise NotFoundException("RazorpayQRCode", qr_id)

    return RazorpayQRResponse(
        id=qr.id,
        razorpay_qr_id=qr.razorpay_qr_id,
        device_id=qr.device.device_id if qr.device else "UNKNOWN",
        slot_number=qr.slot.slot_number if qr.slot else 1,
        product_name=qr.slot.product.name if (qr.slot and qr.slot.product) else "Vending Item",
        amount_rupees=round(qr.amount / 100.0, 2),
        amount_paise=qr.amount,
        usage=qr.usage,
        qr_payload=qr.qr_payload,
        image_url=qr.image_url,
        status=qr.status,
    )


@router.post("/razorpay/verify-payment", response_model=RazorpayVerifyPaymentResponse)
def verify_payment_endpoint(
    payload: RazorpayVerifyPaymentRequest,
):
    """
    Verify payment signature for client-side Razorpay Checkout transactions.
    """
    is_valid = verify_payment_signature(
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        razorpay_signature=payload.razorpay_signature,
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Razorpay payment signature.",
        )
    return RazorpayVerifyPaymentResponse(
        valid=True,
        message="Payment signature verified successfully.",
    )


@router.get("/webhook-events", tags=["Razorpay Audit & Monitoring"])
def list_webhook_events(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    [Admin / Diagnostic Endpoint]
    Retrieve recent incoming webhook events and their processing status.
    """
    events = (
        db.query(WebhookEvent)
        .order_by(WebhookEvent.received_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    return [
        {
            "id": evt.id,
            "event_id": evt.event_id,
            "event_type": evt.event_type,
            "gateway": evt.gateway,
            "status": evt.status,
            "received_at": evt.received_at.isoformat() if evt.received_at else None,
            "processed_at": evt.processed_at.isoformat() if evt.processed_at else None,
            "error_message": evt.error_message,
        }
        for evt in events
    ]
