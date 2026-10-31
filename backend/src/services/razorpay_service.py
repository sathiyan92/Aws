"""
Razorpay Payment Gateway Service (Development & Test Mode).
Handles:
1. Raw-body HMAC-SHA256 webhook signature verification.
2. Idempotent webhook event processing with duplicate-event protection (WebhookEvent table).
3. Razorpay dynamic and static QR Code generation (with live API integration and mock fallback).
4. Automated machine slot price matching and dispense authorization.
5. Zero-leakage credential safety (secrets strictly on backend).
"""
import hmac
import hashlib
import json
import base64
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Tuple
import requests
from sqlalchemy.orm import Session

from src.core.config.settings import settings
from src.db.base import utc_now, generate_uuid
from src.db.models.device import Device
from src.db.models.vending import Order, Payment, MachineSlot, WebhookEvent, RazorpayQRCode
from src.db.models.audit import AuditLog
from src.core.exceptions.errors import (
    BadRequestException,
    NotFoundException,
    NotAuthenticatedException,
)


RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


def verify_webhook_signature(
    raw_body: bytes,
    signature: str,
    secret: Optional[str] = None,
) -> bool:
    """
    Verify Razorpay webhook signature using raw request body bytes and HMAC SHA-256.
    
    Header received from Razorpay: 'X-Razorpay-Signature'
    """
    webhook_secret = secret or settings.RAZORPAY_WEBHOOK_SECRET
    if not webhook_secret or not signature:
        return False

    expected_signature = hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_signature, signature)


def verify_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
    secret: Optional[str] = None,
) -> bool:
    """
    Verify standard Razorpay Checkout payment signature (order_id|payment_id).
    Used when frontend modal completes payment.
    """
    key_secret = secret or settings.RAZORPAY_KEY_SECRET
    if not key_secret or not razorpay_signature:
        return False

    msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8")
    expected_sig = hmac.new(
        key=key_secret.encode("utf-8"),
        msg=msg,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(expected_sig, razorpay_signature)


def create_razorpay_order(
    db: Session,
    device_id: str,
    slot_number: int = 1,
    amount_rupees: Optional[float] = None,
    customer_phone: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create an official Razorpay Order via POST /v1/orders.
    Also creates a corresponding PENDING Order in local database.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.mac_address.ilike(device_id.strip()))
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    slot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=slot_number).first()
    if not slot and device.slots:
        slot = device.slots[0]

    if amount_rupees is not None:
        amount_paise = int(amount_rupees * 100)
    elif slot:
        amount_paise = slot.override_price if slot.override_price is not None else (slot.product.price if slot.product else 1000)
    else:
        amount_paise = 1000

    now = utc_now()
    receipt_no = f"rcpt_{device.device_id}_{int(now.timestamp())}"
    product_name = slot.product.name if (slot and slot.product) else "Vending Item"

    has_live_keys = (
        bool(settings.RAZORPAY_KEY_ID)
        and settings.RAZORPAY_KEY_ID != "rzp_test_placeholder"
        and bool(settings.RAZORPAY_KEY_SECRET)
        and settings.RAZORPAY_KEY_SECRET != "placeholder_secret"
    )

    razorpay_order_id = None
    if has_live_keys:
        try:
            resp = requests.post(
                f"{RAZORPAY_API_BASE}/orders",
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                json={
                    "amount": amount_paise,
                    "currency": settings.RAZORPAY_CURRENCY,
                    "receipt": receipt_no[:40],
                    "notes": {
                        "device_id": device.device_id,
                        "slot_number": str(slot.slot_number if slot else 1),
                        "product_name": product_name,
                    },
                },
                timeout=10,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                razorpay_order_id = data.get("id")
        except Exception:
            pass

    if not razorpay_order_id:
        razorpay_order_id = f"order_mock_{generate_uuid()[:14]}"

    order_uuid = generate_uuid()
    order_number = f"ORD-{now.strftime('%Y%m%d')}-{generate_uuid()[:6].upper()}"
    local_order = Order(
        id=order_uuid,
        order_number=order_number,
        device_id=device.id,
        client_id=device.client_id,
        slot_id=slot.id if slot else None,
        product_id=slot.product_id if slot else None,
        unit_price=amount_paise,
        quantity=1,
        total_amount=amount_paise,
        order_status="PENDING",
        payment_method="RAZORPAY",
    )
    db.add(local_order)

    payment = Payment(
        order_id=local_order.id,
        client_id=device.client_id,
        gateway_provider="RAZORPAY",
        gateway_payment_intent_id=razorpay_order_id,
        razorpay_order_id=razorpay_order_id,
        amount=amount_paise,
        currency=settings.RAZORPAY_CURRENCY,
        payment_status="INITIATED",
        paid_at=None,
    )
    db.add(payment)
    db.commit()

    return {
        "order_id": local_order.id,
        "order_number": order_number,
        "razorpay_order_id": razorpay_order_id,
        "amount_paise": amount_paise,
        "amount_rupees": round(amount_paise / 100.0, 2),
        "currency": settings.RAZORPAY_CURRENCY,
        "key_id": settings.RAZORPAY_KEY_ID,
        "device_id": device.device_id,
        "slot_number": slot.slot_number if slot else 1,
        "product_name": product_name,
    }


def process_webhook_event(
    db: Session,
    raw_body: bytes,
    signature: Optional[str],
    enforce_signature: bool = True,
) -> Dict[str, Any]:
    """
    Process incoming Razorpay webhook event with strict signature verification
    and idempotent duplicate-event protection.
    
    Returns standard status dict and HTTP status code.
    """
    # 1. Parse JSON payload from raw body
    try:
        body_text = raw_body.decode("utf-8")
        webhook_data = json.loads(body_text) if body_text else {}
    except Exception as e:
        raise BadRequestException(f"Invalid JSON payload: {str(e)}")

    event_type = webhook_data.get("event", "unknown")
    event_id = webhook_data.get("id") or webhook_data.get("event_id")

    # If top-level id is missing, construct deterministic event_id from payment entity
    payment_entity = webhook_data.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    if not event_id:
        if payment_id:
            event_id = f"evt_{event_type}_{payment_id}"
        else:
            event_id = f"evt_{event_type}_{hashlib.md5(raw_body).hexdigest()[:16]}"

    # 2. Signature Verification
    # In production or when secrets are configured, signature must match.
    # In test mode with default placeholder credentials, we verify if signature is provided.
    is_signature_valid = False
    if signature:
        is_signature_valid = verify_webhook_signature(raw_body, signature)

    if enforce_signature and not is_signature_valid:
        # Check if developer is using default placeholder in dev/test environment
        is_placeholder_secret = settings.RAZORPAY_WEBHOOK_SECRET == "placeholder_webhook_secret"
        if not (settings.RAZORPAY_TEST_MODE and is_placeholder_secret and signature == "test_dev_bypass"):
            # Record failed event attempt
            failed_log = WebhookEvent(
                event_id=f"invalid_sig_{event_id}_{generate_uuid()[:8]}",
                event_type=event_type,
                gateway="RAZORPAY",
                status="FAILED",
                payload=webhook_data,
                error_message="Invalid HMAC SHA-256 webhook signature (X-Razorpay-Signature mismatch)",
                received_at=utc_now(),
                processed_at=utc_now(),
            )
            db.add(failed_log)
            db.commit()
            raise NotAuthenticatedException("Invalid Razorpay webhook signature.")

    # 3. Idempotency Check (Duplicate-Event Protection)
    existing_event = db.query(WebhookEvent).filter(WebhookEvent.event_id == event_id).first()
    if existing_event:
        if existing_event.status in ("PROCESSED", "DUPLICATE_IGNORED"):
            return {
                "status": "DUPLICATE_IGNORED",
                "event_id": event_id,
                "event_type": event_type,
                "message": "Webhook event was already processed previously.",
            }

    # Record incoming event record
    webhook_record = existing_event or WebhookEvent(
        event_id=event_id,
        event_type=event_type,
        gateway="RAZORPAY",
        status="RECEIVED",
        payload=webhook_data,
        received_at=utc_now(),
    )
    if not existing_event:
        db.add(webhook_record)
        db.flush()

    # 4. Handle Specific Event Types
    try:
        # We process 'payment.captured' and 'qr_code.credited'
        if event_type in ("payment.captured", "qr_code.credited", "payment.authorized"):
            result = _handle_payment_captured(db=db, webhook_data=webhook_data, payment_id=payment_id)
            webhook_record.status = "PROCESSED"
            webhook_record.processed_at = utc_now()
            db.commit()
            return {
                "status": "SUCCESS",
                "event_id": event_id,
                "event_type": event_type,
                "dispense": result,
            }
        else:
            webhook_record.status = "PROCESSED"
            webhook_record.processed_at = utc_now()
            db.commit()
            return {
                "status": "IGNORED",
                "event_id": event_id,
                "event_type": event_type,
                "message": f"Event type '{event_type}' ignored (not a payment event).",
            }
    except Exception as exc:
        db.rollback()
        # Mark as failed in new transaction
        try:
            webhook_record.status = "FAILED"
            webhook_record.error_message = str(exc)
            webhook_record.processed_at = utc_now()
            db.add(webhook_record)
            db.commit()
        except Exception:
            pass
        raise


def _handle_payment_captured(
    db: Session,
    webhook_data: Dict[str, Any],
    payment_id: Optional[str],
) -> Dict[str, Any]:
    """
    Handle captured payment by matching target device, resolving slot,
    verifying payment status and expected amount, creating/updating Order & Payment records,
    issuing a unique one-time dispense token with offline retention, and logging complete audit details.
    """
    payload_obj = webhook_data.get("payload", {})
    payment_entity = payload_obj.get("payment", {}).get("entity", {})
    qr_entity = payload_obj.get("qr_code", {}).get("entity", {})

    p_id = payment_id or payment_entity.get("id") or "pay_simulated"
    qr_id = (
        qr_entity.get("id")
        or payment_entity.get("notes", {}).get("razorpay_qr_id")
        or qr_entity.get("notes", {}).get("razorpay_qr_id")
        or payment_entity.get("notes", {}).get("qr_id")
    )

    # 1. Verify Payment Status (Requirement 4)
    payment_status = (payment_entity.get("status") or "captured").lower()
    if payment_status not in ("captured", "authorized", "paid"):
        raise BadRequestException(f"Payment status '{payment_status}' is not captured/authorized.")

    amount_paise = payment_entity.get("amount") or qr_entity.get("payment_amount") or 0
    currency = payment_entity.get("currency") or qr_entity.get("currency") or "INR"
    notes = payment_entity.get("notes") or qr_entity.get("notes") or {}

    device_id_note = (
        notes.get("device_id")
        or notes.get("machine_id")
        or notes.get("deviceId")
    )
    slot_number_note = notes.get("slot_number") or notes.get("slot")

    # 2. Find corresponding RazorpayQRCode and Order via stored QR ID (Requirements 2, 3 & 5)
    qr_record = None
    if qr_id:
        qr_record = db.query(RazorpayQRCode).filter(RazorpayQRCode.razorpay_qr_id == str(qr_id)).first()

    matched_order = None
    if qr_id:
        matched_order = db.query(Order).filter(Order.razorpay_qr_id == str(qr_id)).first()
    if not matched_order:
        order_id_note = notes.get("order_id") or notes.get("order_number")
        if order_id_note:
            matched_order = db.query(Order).filter(
                (Order.id == str(order_id_note)) | (Order.order_number == str(order_id_note))
            ).first()

    # 3. Resolve Target Machine with Strict Machine Isolation (Requirements 5 & 12)
    device = None
    if qr_record:
        device = qr_record.device or db.query(Device).filter(Device.id == qr_record.device_id).first()
    elif matched_order:
        device = matched_order.device or db.query(Device).filter(Device.id == matched_order.device_id).first()

    if not device and device_id_note:
        device = db.query(Device).filter(
            (Device.device_id == str(device_id_note)) | (Device.mac_address.ilike(str(device_id_note).strip()))
        ).first()

    # Only in single-machine dev/test environments with no ambiguous identifier
    if not device and not qr_id and not device_id_note:
        active_devices = db.query(Device).filter(Device.status == "ACTIVE").all()
        if len(active_devices) == 1:
            device = active_devices[0]

    if not device:
        raise NotFoundException("Device", device_id_note or qr_id or "Unspecified in webhook payment notes")

    # 4. Verify Amount Matches Expected Order/QR Amount (Requirement 4)
    expected_amount = None
    if matched_order:
        expected_amount = matched_order.total_amount
    elif qr_record:
        expected_amount = qr_record.amount

    if expected_amount is not None and amount_paise != expected_amount:
        raise BadRequestException(
            f"Payment amount mismatch: received {amount_paise} paise, expected {expected_amount} paise."
        )

    # 5. Price & Slot Resolution
    slot = None
    if qr_record and qr_record.slot_id:
        slot = db.query(MachineSlot).filter_by(id=qr_record.slot_id).first()
    if not slot and matched_order and matched_order.slot_id:
        slot = matched_order.slot

    if not slot and slot_number_note:
        try:
            slot_num = int(slot_number_note)
            slot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=slot_num).first()
        except (ValueError, TypeError):
            pass

    if not slot:
        # Match incoming amount to configured slot price
        for s in device.slots:
            if not s.is_active:
                continue
            slot_price = s.override_price if s.override_price is not None else (s.product.price if s.product else None)
            if slot_price == amount_paise:
                slot = s
                break

    if not slot and device.slots:
        slot = device.slots[0]

    # 6. Idempotency Check on Razorpay Payment ID (Requirement 11)
    if p_id and p_id != "pay_simulated":
        existing_payment = db.query(Payment).filter(Payment.razorpay_payment_id == p_id).first()
        if existing_payment and existing_payment.payment_status == "SUCCESS":
            existing_ord = existing_payment.order
            return {
                "order_id": existing_ord.id if existing_ord else None,
                "order_number": existing_ord.order_number if existing_ord else None,
                "device_id": device.device_id,
                "slot_number": slot.slot_number if slot else 1,
                "amount_rupees": round(amount_paise / 100.0, 2),
                "status": existing_ord.order_status if existing_ord else "PAID",
                "message": "Payment already captured previously.",
            }

    now = utc_now()
    # Unique one-time dispense authorization with offline retention (Requirements 7 & 14)
    dispense_token = f"auth_{generate_uuid()}"
    hold_minutes = getattr(settings, "OFFLINE_DISPENSE_HOLD_MINUTES", 60)
    dispense_token_expires_at = now + timedelta(minutes=hold_minutes)

    # 7. Create or update Order marked as PAID (Requirement 6)
    if matched_order and matched_order.order_status in ("PENDING", "PAYMENT_PENDING"):
        order = matched_order
        order.order_status = "PAID"
        order.payment_method = "RAZORPAY"
        order.paid_at = now
        order.dispense_token = dispense_token
        order.dispense_token_expires_at = dispense_token_expires_at
        if qr_id and not order.razorpay_qr_id:
            order.razorpay_qr_id = qr_id
        order_number = order.order_number
        order_id = order.id
    else:
        order_id = generate_uuid()
        order_number = f"ORD-{now.strftime('%Y%m%d')}-{generate_uuid()[:6].upper()}"
        order = Order(
            id=order_id,
            order_number=order_number,
            device_id=device.id,
            client_id=device.client_id,
            slot_id=slot.id if slot else None,
            product_id=slot.product_id if slot else None,
            unit_price=amount_paise,
            quantity=1,
            total_amount=amount_paise,
            order_status="PAID",
            payment_method="RAZORPAY",
            razorpay_qr_id=qr_id,
            paid_at=now,
            dispense_token=dispense_token,
            dispense_token_expires_at=dispense_token_expires_at,
        )
        db.add(order)

    # 8. Record or update Payment
    existing_payment = db.query(Payment).filter(Payment.order_id == order.id).first()
    if existing_payment:
        payment = existing_payment
        payment.gateway_provider = "RAZORPAY"
        payment.gateway_payment_intent_id = p_id
        payment.gateway_transaction_id = p_id
        payment.razorpay_payment_id = p_id
        payment.amount = amount_paise
        payment.currency = currency
        payment.payment_status = "SUCCESS"
        payment.raw_gateway_response = payment_entity or qr_entity
        payment.paid_at = now
    else:
        payment = Payment(
            order_id=order.id,
            client_id=device.client_id,
            gateway_provider="RAZORPAY",
            gateway_payment_intent_id=p_id,
            gateway_transaction_id=p_id,
            razorpay_payment_id=p_id,
            amount=amount_paise,
            currency=currency,
            payment_status="SUCCESS",
            raw_gateway_response=payment_entity or qr_entity,
            paid_at=now,
        )
        db.add(payment)

    # 9. Audit Log with Full Traceability (Requirement 13)
    db.add(AuditLog(
        client_id=device.client_id,
        user_id=None,
        action="RAZORPAY_WEBHOOK_PAYMENT_CAPTURED",
        entity_type="ORDER",
        entity_id=order.id,
        old_state={"payment_id": p_id, "status": "PENDING"},
        new_state={
            "payment_id": p_id,
            "razorpay_qr_id": qr_id,
            "order_id": order.id,
            "order_number": order_number,
            "machine_id": device.device_id,
            "vendor_id": device.client_id,
            "amount_paise": amount_paise,
            "amount_rupees": round(amount_paise / 100.0, 2),
            "currency": currency,
            "dispense_token": dispense_token,
            "dispense_token_expires_at": str(dispense_token_expires_at),
            "status": "PAID",
            "timestamp": str(now),
        },
    ))

    return {
        "order_id": order.id,
        "order_number": order_number,
        "device_id": device.device_id,
        "slot_number": slot.slot_number if slot else 1,
        "amount_rupees": round(amount_paise / 100.0, 2),
        "dispense_token": dispense_token,
        "status": "PAID",
    }


def create_razorpay_qr(
    db: Session,
    device_id: str,
    slot_number: Optional[int] = 1,
    amount_rupees: Optional[float] = None,
    usage: str = "single_use",
    name_override: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a Razorpay dynamic or static UPI QR code.
    If real Razorpay API keys are configured, calls Razorpay QR API.
    If in Test Mode or placeholder credentials, generates standard UPI URI and mock QR entity.
    Stores record in razorpay_qr_codes table.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.mac_address.ilike(device_id.strip()))
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    slot = None
    if slot_number:
        slot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=slot_number).first()
    if not slot and device.slots:
        slot = device.slots[0]

    # Resolve price
    if amount_rupees is not None:
        amount_paise = int(amount_rupees * 100)
    elif slot:
        amount_paise = slot.override_price if slot.override_price is not None else (slot.product.price if slot.product else 1000)
    else:
        amount_paise = 1000

    amount_in_rupees = round(amount_paise / 100.0, 2)
    product_name = (slot.product.name if (slot and slot.product) else "Vending Item")
    qr_name = name_override or f"{device.device_id} - Slot {slot.slot_number if slot else 1}"

    # Determine if real Razorpay keys are configured
    has_live_keys = (
        bool(settings.RAZORPAY_KEY_ID)
        and settings.RAZORPAY_KEY_ID != "rzp_test_placeholder"
        and bool(settings.RAZORPAY_KEY_SECRET)
        and settings.RAZORPAY_KEY_SECRET != "placeholder_secret"
    )

    qr_id = None
    image_url = None
    qr_payload = None

    if has_live_keys:
        try:
            # Call official Razorpay QR API
            auth_header = (settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
            payload = {
                "type": "upi_qr",
                "name": qr_name[:40],
                "usage": usage,
                "fixed_amount": True,
                "payment_amount": amount_paise,
                "description": product_name[:30],
                "notes": {
                    "device_id": device.device_id,
                    "slot_number": str(slot.slot_number if slot else 1),
                },
            }
            resp = requests.post(
                f"{RAZORPAY_API_BASE}/payments/qr_codes",
                json=payload,
                auth=auth_header,
                timeout=10,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                qr_id = data.get("id")
                image_url = data.get("image_url")
                # Requirement 15: Do NOT encode image_url as qr_payload. Construct direct UPI deep-link.
                vpa = getattr(settings, "RAZORPAY_UPI_VPA", "gtech282722.rzp@rxairtel") or f"rzp.vending.{device.device_id.lower()}@icici"
                encoded_name = urllib.parse.quote(qr_name)
                qr_payload = f"upi://pay?pa={vpa}&pn={encoded_name}&am={amount_in_rupees:.2f}&cu=INR&tn={device.device_id}&tr={qr_id}"
        except Exception as e:
            # Fall back to UPI generation
            pass

    # If mock/test mode or API call didn't execute
    if not qr_id or not qr_payload:
        generated_nonce = generate_uuid()[:8]
        qr_id = f"qr_test_{device.device_id.lower()}_{generated_nonce}"
        vpa = getattr(settings, "RAZORPAY_UPI_VPA", "gtech282722.rzp@rxairtel") or f"rzp.vending.{device.device_id.lower()}@icici"
        encoded_name = urllib.parse.quote(qr_name)
        qr_payload = f"upi://pay?pa={vpa}&pn={encoded_name}&am={amount_in_rupees:.2f}&cu=INR&tn={device.device_id}&tr={qr_id}"
        image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=300x300&data={urllib.parse.quote(qr_payload)}"

    # Save to razorpay_qr_codes table
    qr_record = RazorpayQRCode(
        client_id=device.client_id,
        device_id=device.id,
        slot_id=slot.id if slot else None,
        razorpay_qr_id=qr_id,
        name=qr_name,
        usage=usage,
        fixed_amount=True,
        amount=amount_paise,
        currency="INR",
        qr_payload=qr_payload,
        image_url=image_url,
        status="active",
        notes={"device_id": device.device_id, "slot_number": slot.slot_number if slot else 1},
    )
    db.add(qr_record)
    db.commit()
    db.refresh(qr_record)

    return {
        "id": qr_record.id,
        "razorpay_qr_id": qr_record.razorpay_qr_id,
        "device_id": device.device_id,
        "slot_number": slot.slot_number if slot else 1,
        "product_name": product_name,
        "amount_rupees": amount_in_rupees,
        "amount_paise": amount_paise,
        "usage": usage,
        "qr_payload": qr_payload,
        "image_url": image_url,
        "status": qr_record.status,
    }
