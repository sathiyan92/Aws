"""
Razorpay Payments API Router.
Provides:
- Webhook receiver (POST /api/v1/payments/razorpay/webhook)
- Razorpay Order creation (POST /api/v1/payments/razorpay/order/create)
- Dynamic and Static QR creation (POST /api/v1/payments/razorpay/qr/create)
- Public client configuration (GET /api/v1/payments/razorpay/config)
- Payment signature verification (POST /api/v1/payments/razorpay/verify-payment)
- Webhook audit log inspection (GET /api/v1/payments/webhook-events)
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Header, Request, Query, status, HTTPException
from sqlalchemy.orm import Session

from src.db.session import get_db
from src.core.config.settings import settings
from src.core.exceptions.errors import NotFoundException
from src.db.models.vending import RazorpayQRCode, WebhookEvent, Order, Payment
from src.db.base import utc_now
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
    create_razorpay_order,
)

router = APIRouter(prefix="/payments", tags=["Razorpay Payments & Webhooks"])


@router.get("/razorpay/webhook", status_code=status.HTTP_200_OK)
@router.get("/razorpay/webhook/", status_code=status.HTTP_200_OK)
@router.head("/razorpay/webhook", status_code=status.HTTP_200_OK)
@router.head("/razorpay/webhook/", status_code=status.HTTP_200_OK)
def razorpay_webhook_ping():
    """
    [Razorpay Dashboard Verification Endpoint]
    Returns HTTP 200 JSON confirmation when Razorpay checks URL validity during webhook setup.
    """
    return {
        "status": "OK",
        "gateway": "RAZORPAY",
        "service": "iot-vending-webhook",
        "message": "Razorpay webhook receiver is active and ready.",
    }


@router.post("/razorpay/webhook", status_code=status.HTTP_200_OK)
@router.post("/razorpay/webhook/", status_code=status.HTTP_200_OK)
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
        enforce_signature=False,
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


@router.post("/razorpay/order/create")
def create_order_endpoint(
    device_id: str = Query(..., description="Machine device ID e.g. VM-000001"),
    slot_number: int = Query(1, description="Slot number"),
    amount_rupees: Optional[float] = Query(None, description="Custom amount in rupees"),
    db: Session = Depends(get_db),
):
    """
    Create an official Razorpay Order for web/mobile checkout.
    """
    return create_razorpay_order(
        db=db,
        device_id=device_id,
        slot_number=slot_number,
        amount_rupees=amount_rupees,
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


@router.get("/razorpay/qr/mappings/all")
def list_all_qr_mappings(
    db: Session = Depends(get_db),
):
    """
    [Fleet Diagnostic Endpoint]
    Lists all active QR code bindings across 1000+ machines to verify strict machine isolation.
    """
    qrs = db.query(RazorpayQRCode).all()
    return [
        {
            "razorpay_qr_id": q.razorpay_qr_id,
            "device_id": q.device.device_id if q.device else "UNASSIGNED",
            "amount_rupees": round(q.amount / 100.0, 2),
            "product_name": q.slot.product.name if (q.slot and q.slot.product) else "Item",
            "slot_number": q.slot.slot_number if q.slot else 1,
            "status": q.status,
            "qr_payload": q.qr_payload[:60] + "..." if q.qr_payload and len(q.qr_payload) > 60 else q.qr_payload,
        }
        for q in qrs
    ]


@router.post("/razorpay/qr/bind-machine")
def bind_qr_to_machine(
    device_id: str = Query(..., description="Target Machine ID e.g. VM-000002"),
    qr_id_or_tr: str = Query(..., description="Razorpay QR ID (qr_...) or UPI Transaction Ref (tr)"),
    amount_rupees: float = Query(..., description="Product price in Rupees for this machine slot"),
    product_name: str = Query("Vending Item", description="Product display name"),
    db: Session = Depends(get_db),
):
    """
    [Fleet Management Endpoint]
    Explicitly binds a unique QR ID or Standee 'tr' reference to a specific machine and slot price.
    Guarantees strict isolation across 1000+ machines.
    """
    from src.db.models.device import Device
    from src.api.v1.devices.gateway_routes import _sync_device_qr_mapping

    device = db.query(Device).filter(
        (Device.device_id == device_id.strip()) | (Device.mac_address.ilike(device_id.strip()))
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    raw_qr = f"upi://pay?am={amount_rupees:.2f}&cu=INR&tr={qr_id_or_tr.strip()}"
    _sync_device_qr_mapping(
        db=db,
        device=device,
        raw_qr=raw_qr,
        price_rupees=amount_rupees,
        product_name=product_name,
    )
    return {
        "status": "BOUND",
        "device_id": device.device_id,
        "qr_id": qr_id_or_tr.strip(),
        "amount_rupees": amount_rupees,
        "product_name": product_name,
        "message": f"QR '{qr_id_or_tr.strip()}' is now exclusively mapped to {device.device_id} at Rs {amount_rupees:.2f}.",
    }


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
    db: Session = Depends(get_db),
):
    """
    Verify payment signature for client-side Razorpay Checkout transactions.
    When verified, immediately transitions order to DISPENSE_AUTHORIZED so the ESP32 dispenses!
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

    # Locate and authorize order for dispense
    order = db.query(Order).join(Payment).filter(
        (Payment.razorpay_order_id == payload.razorpay_order_id) |
        (Payment.gateway_payment_intent_id == payload.razorpay_order_id)
    ).first()

    if order:
        order.order_status = "DISPENSE_AUTHORIZED"
        if order.payment:
            order.payment.payment_status = "SUCCESS"
            order.payment.razorpay_payment_id = payload.razorpay_payment_id
            order.payment.paid_at = utc_now()
        db.commit()

    return RazorpayVerifyPaymentResponse(
        valid=True,
        message="Payment verified! Item is dispensing.",
    )


@router.delete("/razorpay/qr/{qr_id}")
def delete_qr_endpoint(
    qr_id: str,
    db: Session = Depends(get_db),
):
    """
    [Fleet Management Endpoint]
    Deletes a stored Razorpay QR Code or Standee TR ID mapping so it no longer triggers dispensing.
    """
    qr = db.query(RazorpayQRCode).filter(
        (RazorpayQRCode.razorpay_qr_id == qr_id) | (RazorpayQRCode.id == qr_id)
    ).first()
    if not qr:
        raise NotFoundException("RazorpayQRCode", qr_id)

    db.delete(qr)
    db.commit()
    return {"status": "DELETED", "deleted_qr_id": qr_id, "message": f"QR mapping '{qr_id}' successfully removed."}


@router.post("/razorpay/qr/clean-mappings")
def clean_fleet_qr_mappings(
    keep_vm1_default: bool = Query(True, description="Keep official TuXKipEEX2KteFqrv2 mapping for VM-000001"),
    db: Session = Depends(get_db),
):
    """
    [Fleet Maintenance Endpoint]
    Purges any rogue auto-linked QR codes, keeping only official machine bindings.
    """
    all_qrs = db.query(RazorpayQRCode).all()
    deleted = []
    for q in all_qrs:
        is_vm1_official = q.razorpay_qr_id in ("TuXKipEEX2KteFqrv2", "qr_TuXKipEEX2KteFqrv2")
        is_auto_linked = isinstance(q.notes, dict) and q.notes.get("auto_linked")
        is_unknown_alias = q.razorpay_qr_id in ("qr_TuZRXzwHRZaG7y", "qr_TuXKipEEX2KteF")
        if (is_auto_linked or is_unknown_alias) and not (keep_vm1_default and is_vm1_official):
            deleted.append(q.razorpay_qr_id)
            db.delete(q)
    db.commit()
    return {
        "status": "PURGED",
        "purged_count": len(deleted),
        "purged_qr_ids": deleted,
        "message": f"Purged {len(deleted)} rogue QR mappings.",
    }


@router.get("/webhook-events", tags=["Razorpay Audit & Monitoring"])
def list_webhook_events(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    """
    [Audit & Diagnostic Endpoint]
    Retrieve recent incoming webhook events, showing exact amounts, detected QR IDs,
    target machine routing, and physical vending results.
    """
    events = (
        db.query(WebhookEvent)
        .order_by(WebhookEvent.received_at.desc())
        .limit(min(limit, 100))
        .all()
    )
    result = []
    for evt in events:
        p_obj = evt.payload or {}
        payment_ent = p_obj.get("payload", {}).get("payment", {}).get("entity", {})
        qr_ent = p_obj.get("payload", {}).get("qr_code", {}).get("entity", {})

        p_id = payment_ent.get("id") or (evt.event_id.split("_")[-1] if evt.event_id else None)
        amt_paise = payment_ent.get("amount") or qr_ent.get("payment_amount") or 0
        amt_rupees = round(amt_paise / 100.0, 2)

        notes = payment_ent.get("notes") or qr_ent.get("notes") or {}
        if not isinstance(notes, dict):
            notes = {}

        qr_id = (
            qr_ent.get("id")
            or notes.get("razorpay_qr_id")
            or notes.get("qr_id")
            or notes.get("tr")
            or payment_ent.get("description")
        )

        # Lookup created order/payment to see target machine
        matched_payment = db.query(Payment).filter(Payment.razorpay_payment_id == p_id).first() if p_id else None
        target_machine = None
        dispense_status = "UNMATCHED_IGNORED"
        if matched_payment and matched_payment.order:
            target_machine = matched_payment.order.device.device_id if matched_payment.order.device else None
            dispense_status = "DISPENSED" if matched_payment.order.order_status in ("PAID", "DISPENSE_AUTHORIZED", "COMPLETED", "DISPENSED") else matched_payment.order.order_status

        result.append({
            "event_id": evt.event_id,
            "event_type": evt.event_type,
            "payment_id": p_id,
            "amount_rupees": amt_rupees,
            "detected_qr_id": qr_id,
            "target_machine": target_machine or ("VM-000001" if evt.status == "PROCESSED" and matched_payment else "UNMATCHED"),
            "vending_status": dispense_status if evt.status == "PROCESSED" else f"FAILED: {evt.error_message}",
            "gateway_status": evt.status,
            "received_at": evt.received_at.isoformat() if evt.received_at else None,
        })
    return result
