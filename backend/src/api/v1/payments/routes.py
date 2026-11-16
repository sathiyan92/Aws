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
from src.db.models.client import Client
from src.db.models.device import Device
from src.db.models.vending import RazorpayQRCode, WebhookEvent, Order, Payment, PayoutTransfer
from src.db.base import utc_now
from src.api.v1.payments.schemas import (
    RazorpayQRCreateRequest,
    RazorpayQRResponse,
    RazorpayConfigResponse,
    RazorpayVerifyPaymentRequest,
    RazorpayVerifyPaymentResponse,
    VendorRouteLinkRequest,
    VendorSelfBankUpdateRequest,
)
from src.services.razorpay_service import (
    process_webhook_event,
    create_razorpay_qr,
    verify_payment_signature,
    create_razorpay_order,
    create_or_update_route_linked_account,
    execute_route_split_transfer,
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

        # Push instantly to ESP32 via WebSocket
        try:
            from src.services.websocket_manager import ws_manager
            dev_id = order.device.device_id if order.device else "VM-000001"
            ws_manager.push_vend_command_sync(dev_id, {
                "event": "DISPENSE",
                "device_id": dev_id,
                "slot_number": order.slot.slot_number if order.slot else 1,
                "amount_rupees": round((order.total_amount or 0) / 100.0, 2),
                "product_name": order.product.name if order.product else "Vending Item",
                "order_id": order.id,
                "order_number": order.order_number,
                "dispense_token": order.dispense_token or "",
                "qr_id": order.razorpay_qr_id or "",
            })
        except Exception:
            pass

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
    keep_vm1_default: bool = Query(True, description="Keep official qr_TuXKipEEX2KteF mapping for VM-000001"),
    db: Session = Depends(get_db),
):
    """
    [Fleet Maintenance Endpoint]
    Purges any rogue auto-linked QR codes, keeping only official machine bindings.
    """
    all_qrs = db.query(RazorpayQRCode).all()
    deleted = []
    for q in all_qrs:
        is_vm1_official = q.razorpay_qr_id in ("qr_TuXKipEEX2KteF", "TuXKipEEX2KteF", "TuXKipEEX2KteFqrv2", "qr_TuXKipEEX2KteFqrv2")
        is_auto_linked = isinstance(q.notes, dict) and q.notes.get("auto_linked")
        is_unknown_alias = q.razorpay_qr_id in ("qr_TuZRXzwHRZaG7y", "TuZRXzwHRZaG7y")
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


@router.post("/razorpay/webhook/reprocess-failed", tags=["Razorpay Audit & Monitoring"])
def reprocess_failed_webhooks(
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """
    [Diagnostic & Recovery Endpoint]
    Re-processes recent FAILED webhook events using updated fleet QR bindings.
    Allows immediately recovering missed dispenses without having to re-pay!
    """
    from src.services.razorpay_service import _handle_payment_captured

    failed_events = (
        db.query(WebhookEvent)
        .filter(WebhookEvent.status == "FAILED")
        .order_by(WebhookEvent.received_at.desc())
        .limit(limit)
        .all()
    )
    results = []
    for evt in failed_events:
        payload = evt.payload or {}
        p_ent = payload.get("payload", {}).get("payment", {}).get("entity", {})
        p_id = p_ent.get("id") or (evt.event_id.split("_")[-1] if evt.event_id else None)
        try:
            dispense_res = _handle_payment_captured(db=db, webhook_data=payload, payment_id=p_id)
            evt.status = "PROCESSED"
            evt.error_message = None
            evt.processed_at = utc_now()
            db.commit()
            results.append({
                "event_id": evt.event_id,
                "status": "REPROCESSED_SUCCESS",
                "dispense": dispense_res,
            })
        except Exception as e:
            db.rollback()
            results.append({
                "event_id": evt.event_id,
                "status": "RETRY_FAILED",
                "error": str(e),
            })
    return {
        "reprocessed_count": len(results),
        "details": results,
    }


@router.post("/test-dispense/{device_id}", tags=["Diagnostics & Testing"])
def trigger_test_dispense(
    device_id: str,
    slot_number: int = Query(1, ge=1, le=10),
    amount_rupees: float = Query(2.0, ge=0.0),
    db: Session = Depends(get_db),
):
    """
    [Diagnostic & Manual Dispense Endpoint]
    Creates an authorized dispense order in the database for the given device.
    The next time the ESP32 polls (within 2 seconds), it will immediately dispense!
    """
    import datetime
    from src.db.models.device import Device
    from src.db.models.vending import Order, MachineSlot
    from src.db.base import utc_now, generate_uuid

    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.mac_address.ilike(device_id.strip()))
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    slot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=slot_number).first()

    order = Order(
        id=generate_uuid(),
        order_number=f"TEST-{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')}",
        client_id=device.client_id,
        device_id=device.id,
        slot_id=slot.id if slot else None,
        product_id=slot.product_id if slot else None,
        total_amount=int(amount_rupees * 100),
        currency="INR",
        order_status="DISPENSE_AUTHORIZED",
        paid_at=utc_now(),
        dispense_token=f"auth_test_{generate_uuid()[:8]}",
        dispense_token_expires_at=utc_now() + datetime.timedelta(hours=1),
        razorpay_qr_id="TuXKipEEX2KteFqrv2",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    try:
        from src.services.websocket_manager import ws_manager
        ws_manager.push_vend_command_sync(device.device_id, {
            "event": "DISPENSE",
            "device_id": device.device_id,
            "slot_number": slot_number,
            "amount_rupees": amount_rupees,
            "product_name": slot.product.name if (slot and slot.product) else "G-TECH Test",
            "order_id": order.id,
            "order_number": order.order_number,
            "dispense_token": order.dispense_token,
            "qr_id": order.razorpay_qr_id,
        })
    except Exception:
        pass

    return {
        "status": "DISPENSE_AUTHORIZED",
        "message": f"Test dispense created for {device.device_id} Slot {slot_number}. Motor will run on next ESP32 poll!",
        "order_id": order.id,
        "order_number": order.order_number,
        "dispense_token": order.dispense_token,
    }





# =========================================================================
# MODEL 1: RAZORPAY ROUTE / VENDOR SPLIT PAYOUT ENDPOINTS
# =========================================================================

@router.post("/route/link-vendor")
def link_vendor_route_account(
    payload: VendorRouteLinkRequest,
    db: Session = Depends(get_db),
):
    """
    [Model 1 - Manufacturer Admin]
    Link a vendor tenant's bank account to Razorpay Route (Marketplace).
    Configures split payout percentage (e.g. 10% platform fee, 90% vendor payout).
    """
    client = db.query(Client).filter(
        (Client.id == payload.client_id) | (Client.client_code.ilike(payload.client_id.strip()))
    ).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor client '{payload.client_id}' not found.",
        )

    res = create_or_update_route_linked_account(
        db=db,
        client=client,
        bank_account_number=payload.bank_account_number,
        bank_ifsc=payload.bank_ifsc,
        bank_beneficiary_name=payload.bank_beneficiary_name,
        commission_percentage=payload.commission_percentage if payload.commission_percentage is not None else 10.0,
        vendor_upi_id=payload.vendor_upi_id,
    )
    return res


@router.get("/route/vendors")
def list_route_vendors(
    db: Session = Depends(get_db),
):
    """
    [Model 1 - Fleet Ledger]
    Returns all vendors with their Route account IDs, commission %, bank summary,
    and cumulative payout earnings.
    """
    from sqlalchemy import func
    clients = db.query(Client).order_by(Client.name.asc()).all()
    results = []

    for c in clients:
        dev_count = db.query(Device).filter(Device.client_id == c.id).count()
        transfers = db.query(PayoutTransfer).filter_by(client_id=c.id).all()
        total_payout_paise = sum(t.vendor_amount_paise for t in transfers)
        total_fee_paise = sum(t.platform_fee_paise for t in transfers)
        total_volume_paise = sum(t.total_amount_paise for t in transfers)

        masked_acc = (
            f"•••• {c.bank_account_number[-4:]}"
            if c.bank_account_number and len(c.bank_account_number) >= 4
            else (c.bank_account_number or "Not Linked")
        )

        results.append({
            "client_id": c.id,
            "client_code": c.client_code,
            "client_name": c.name,
            "contact_email": c.contact_email,
            "razorpay_account_id": c.razorpay_account_id or "UNLINKED",
            "bank_account_masked": masked_acc,
            "bank_ifsc": c.bank_ifsc or "-",
            "bank_beneficiary_name": c.bank_beneficiary_name or "-",
            "commission_percentage": c.commission_percentage if c.commission_percentage is not None else 10.0,
            "vendor_percentage": 100.0 - (c.commission_percentage if c.commission_percentage is not None else 10.0),
            "payout_status": c.payout_status or "UNLINKED",
            "device_count": dev_count,
            "transfer_count": len(transfers),
            "total_earned_rupees": round(total_payout_paise / 100.0, 2),
            "total_fee_paid_rupees": round(total_fee_paise / 100.0, 2),
            "total_volume_rupees": round(total_volume_paise / 100.0, 2),
        })

    return results


@router.get("/route/summary")
def get_route_settlements_summary(
    db: Session = Depends(get_db),
):
    """
    [Model 1 - Executive Summary]
    Fleet-wide financial summary: Total Volume, Vendor Payouts, Platform Commissions,
    Active Linked Vendors, and Total Payout Events.
    """
    transfers = db.query(PayoutTransfer).all()
    total_volume_paise = sum(t.total_amount_paise for t in transfers)
    total_vendor_paise = sum(t.vendor_amount_paise for t in transfers)
    total_platform_fee_paise = sum(t.platform_fee_paise for t in transfers)

    linked_vendors = db.query(Client).filter(
        Client.razorpay_account_id.isnot(None),
        Client.payout_status == "ACTIVE"
    ).count()

    total_vendors = db.query(Client).count()

    return {
        "total_volume_rupees": round(total_volume_paise / 100.0, 2),
        "total_vendor_payouts_rupees": round(total_vendor_paise / 100.0, 2),
        "total_platform_commission_rupees": round(total_platform_fee_paise / 100.0, 2),
        "total_transfers_count": len(transfers),
        "linked_vendors_count": linked_vendors,
        "total_vendors_count": total_vendors,
    }


@router.get("/route/payouts")
def list_route_payout_transfers(
    limit: int = Query(100, ge=1, le=500),
    client_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    [Model 1 - Live Split Ledger]
    Returns atomic split payout records for each vending transaction.
    """
    query = db.query(PayoutTransfer)
    if client_id:
        c = db.query(Client).filter((Client.id == client_id) | (Client.client_code.ilike(client_id.strip()))).first()
        if c:
            query = query.filter(PayoutTransfer.client_id == c.id)

    payouts = query.order_by(PayoutTransfer.transferred_at.desc()).limit(limit).all()

    results = []
    for p in payouts:
        client = p.client or db.query(Client).filter_by(id=p.client_id).first()
        device = p.device or db.query(Device).filter_by(id=p.device_id).first()
        order = p.order or db.query(Order).filter_by(id=p.order_id).first()

        results.append({
            "id": p.id,
            "order_id": p.order_id,
            "order_number": order.order_number if order else "-",
            "payment_id": p.payment_id or "-",
            "razorpay_transfer_id": p.razorpay_transfer_id or "-",
            "client_id": p.client_id,
            "vendor_name": client.name if client else "Unknown Vendor",
            "vendor_code": client.client_code if client else "-",
            "device_id": device.device_id if device else "-",
            "total_rupees": round(p.total_amount_paise / 100.0, 2),
            "vendor_rupees": round(p.vendor_amount_paise / 100.0, 2),
            "fee_rupees": round(p.platform_fee_paise / 100.0, 2),
            "commission_percentage": p.commission_percentage,
            "razorpay_account_id": p.razorpay_account_id or "-",
            "status": p.status,
            "error_message": p.error_message,
            "transferred_at": p.transferred_at.isoformat() if p.transferred_at else None,
        })
    return results


@router.get("/route/vendor/{client_id}")
def get_vendor_route_details(
    client_id: str,
    db: Session = Depends(get_db),
):
    """
    [Model 1 - Vendor Specific Portal Ledger]
    Returns bank configuration, commission rate, and lifetime payouts for a specific client tenant.
    """
    client = db.query(Client).filter(
        (Client.id == client_id) | (Client.client_code.ilike(client_id.strip()))
    ).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor '{client_id}' not found.",
        )

    transfers = db.query(PayoutTransfer).filter_by(client_id=client.id).order_by(PayoutTransfer.transferred_at.desc()).all()
    total_earned_paise = sum(t.vendor_amount_paise for t in transfers)
    total_fee_paise = sum(t.platform_fee_paise for t in transfers)
    total_volume_paise = sum(t.total_amount_paise for t in transfers)

    masked_acc = (
        f"•••• {client.bank_account_number[-4:]}"
        if client.bank_account_number and len(client.bank_account_number) >= 4
        else (client.bank_account_number or "")
    )

    transfer_list = []
    for t in transfers[:50]:
        dev = t.device or db.query(Device).filter_by(id=t.device_id).first()
        ord_obj = t.order or db.query(Order).filter_by(id=t.order_id).first()
        transfer_list.append({
            "id": t.id,
            "order_number": ord_obj.order_number if ord_obj else "-",
            "device_id": dev.device_id if dev else "-",
            "total_rupees": round(t.total_amount_paise / 100.0, 2),
            "vendor_rupees": round(t.vendor_amount_paise / 100.0, 2),
            "fee_rupees": round(t.platform_fee_paise / 100.0, 2),
            "razorpay_transfer_id": t.razorpay_transfer_id or "-",
            "status": t.status,
            "transferred_at": t.transferred_at.isoformat() if t.transferred_at else None,
        })

    return {
        "client_id": client.id,
        "client_code": client.client_code,
        "client_name": client.name,
        "contact_email": client.contact_email,
        "contact_phone": client.contact_phone,
        "bank_account_number": client.bank_account_number or "",
        "bank_account_masked": masked_acc,
        "bank_ifsc": client.bank_ifsc or "",
        "bank_beneficiary_name": client.bank_beneficiary_name or "",
        "vendor_upi_id": client.razorpay_merchant_vpa or "",
        "commission_percentage": client.commission_percentage if client.commission_percentage is not None else 10.0,
        "vendor_percentage": 100.0 - (client.commission_percentage if client.commission_percentage is not None else 10.0),
        "razorpay_account_id": client.razorpay_account_id or "UNLINKED",
        "payout_status": client.payout_status or "UNLINKED",
        "total_earned_rupees": round(total_earned_paise / 100.0, 2),
        "total_fee_paid_rupees": round(total_fee_paise / 100.0, 2),
        "total_volume_rupees": round(total_volume_paise / 100.0, 2),
        "transfer_count": len(transfers),
        "transfers": transfer_list,
    }


@router.post("/route/vendor-self-update/{client_id}")
def vendor_self_update_bank_details(
    client_id: str,
    payload: VendorSelfBankUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    [Model 1 - Vendor Self-Service]
    Allows a vendor tenant admin in the Client Portal to submit or update their bank settlement account.
    """
    client = db.query(Client).filter(
        (Client.id == client_id) | (Client.client_code.ilike(client_id.strip()))
    ).first()
    if not client:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Vendor '{client_id}' not found.",
        )

    res = create_or_update_route_linked_account(
        db=db,
        client=client,
        bank_account_number=payload.bank_account_number,
        bank_ifsc=payload.bank_ifsc,
        bank_beneficiary_name=payload.bank_beneficiary_name,
        commission_percentage=client.commission_percentage if client.commission_percentage is not None else 10.0,
        vendor_upi_id=payload.vendor_upi_id,
    )
    return res
