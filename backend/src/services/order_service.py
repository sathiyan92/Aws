"""
Order Service for Vending Machines.
Manages transaction-based dynamic QR purchase intents, dynamic price resolution,
UPI deep-link payload generation, expiration timers, and order lifecycle states.
"""
from typing import List, Optional, Dict, Any
import uuid
import urllib.parse
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from src.core.config.settings import settings
from src.db.base import utc_now, generate_uuid
from src.db.models.device import Device, DeviceModule
from src.db.models.vending import Order, Payment, MachineSlot, Product
from src.db.models.audit import AuditLog
from src.core.exceptions.errors import (
    NotFoundException,
    ForbiddenException,
    BadRequestException,
    ConflictException,
    ModuleDisabledException,
)
from src.api.v1.orders.schemas import (
    OrderInitiateRequest,
    OrderInitiateResponse,
    OrderDetailResponse,
    OrderCancelResponse,
)


def _ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Ensure datetime is timezone-aware UTC for robust comparisons across DB dialects."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def initiate_order(
    db: Session,
    payload: OrderInitiateRequest,
    user_id: Optional[str] = None,
    client_ip: Optional[str] = None,
) -> OrderInitiateResponse:
    """
    Initiate an ephemeral, transaction-based dynamic QR purchase intent.
    Validates machine state, module enablement, and slot inventory.
    Resolves active price dynamically and generates UPI QR payload.
    """
    # 1. Lookup and validate Device
    device = db.query(Device).filter(Device.device_id == payload.device_id).first()
    if not device:
        raise NotFoundException("Device", payload.device_id)

    if device.status == "SUSPENDED":
        raise ForbiddenException(f"Device '{payload.device_id}' is suspended.")

    # 2. Enforce QR_PAYMENT Module Guard
    qr_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="QR_PAYMENT").first()
    if not qr_mod or not qr_mod.is_enabled:
        raise ModuleDisabledException("QR_PAYMENT", device.device_id)

    # 3. Lookup physical Machine Slot
    slot = db.query(MachineSlot).filter_by(
        device_id=device.id,
        slot_number=payload.slot_number,
    ).first()
    if not slot or not slot.is_active:
        raise NotFoundException("MachineSlot", f"Slot {payload.slot_number} on {device.device_id}")

    # 4. Validate Product Mapping and Stock
    if not slot.product or not slot.product.is_active:
        raise BadRequestException(f"Slot {payload.slot_number} has no active product assigned.")

    if slot.current_stock <= 0:
        raise ConflictException(
            f"Slot {payload.slot_number} ({slot.product.name}) is out of stock.",
            error_code="OUT_OF_STOCK",
        )

    # 5. Dynamic Price Resolution: slot price override takes precedence over catalog price
    resolved_price_paise = slot.override_price if slot.override_price is not None else slot.product.price
    amount_rupees = round(resolved_price_paise / 100.0, 2)

    # 6. Extract QR Configuration Parameters
    cfg = qr_mod.configuration or {}
    merchant_vpa = cfg.get("upi_merchant_vpa", f"pay.{device.device_id.lower()}@icici")
    timeout_sec = cfg.get("qr_timeout_seconds", 180)
    provider = cfg.get("provider", "UPI_DYNAMIC")
    client_name = device.client.name if device.client else "IoT Vending"

    # 7. Generate Unique Order Identifiers & Expiration
    now = utc_now()
    order_uuid = str(uuid.uuid4())
    order_number = f"ORD-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    expires_at = now + timedelta(seconds=timeout_sec)

    # 8. Construct Ephemeral Dynamic UPI URI
    # Format: upi://pay?pa={vpa}&pn={name}&am={amount}&cu=INR&tn={order_number}&tr={order_uuid}
    encoded_name = urllib.parse.quote(client_name)
    upi_uri = (
        f"upi://pay?pa={merchant_vpa}&pn={encoded_name}"
        f"&am={amount_rupees:.2f}&cu=INR&tn={order_number}&tr={order_uuid}"
    )

    # 9. ASCII LCD Frame Preview for debugging and embedded testing
    ascii_preview = (
        f"+---------------------------------------+\n"
        f"|         SCAN WITH ANY UPI APP         |\n"
        f"|  {slot.product.name[:25]:<25}    |\n"
        f"|  Price: Rs.{amount_rupees:<6.2f} | Slot: {slot.slot_number:02d}      |\n"
        f"|  Expires in: {timeout_sec:03d}s                     |\n"
        f"|  Order: {order_number}        |\n"
        f"+---------------------------------------+"
    )

    # 10. Persist Order
    order = Order(
        id=order_uuid,
        order_number=order_number,
        client_id=device.client_id,
        device_id=device.id,
        slot_id=slot.id,
        product_id=slot.product_id,
        payment_method="QR_PAYMENT",
        unit_price=resolved_price_paise,
        quantity=1,
        total_amount=resolved_price_paise,
        order_status="PENDING",
        expires_at=expires_at,
    )
    db.add(order)
    db.flush()

    # 11. Persist Dynamic Payment Intent
    payment = Payment(
        order_id=order.id,
        client_id=device.client_id,
        gateway_provider=provider,
        gateway_payment_intent_id=f"intent_{order.order_number}",
        amount=resolved_price_paise,
        currency="INR",
        payment_status="INITIATED",
        raw_gateway_response={
            "upi_uri": upi_uri,
            "merchant_vpa": merchant_vpa,
            "timeout_seconds": timeout_sec,
            "customer_phone": payload.customer_phone,
            "customer_vpa": payload.customer_vpa,
        },
    )
    db.add(payment)

    # 12. Audit Logging
    db.add(AuditLog(
        client_id=device.client_id,
        user_id=user_id,
        action="ORDER_INITIATED",
        entity_type="ORDER",
        entity_id=order.id,
        old_state=None,
        new_state={
            "order_number": order_number,
            "amount_paise": resolved_price_paise,
            "slot_number": slot.slot_number,
            "product_code": slot.product.product_code,
            "device_id": device.device_id,
            "expires_at": expires_at.isoformat(),
        },
        ip_address=client_ip,
    ))

    db.commit()

    return OrderInitiateResponse(
        order_id=order.id,
        order_number=order.order_number,
        device_id=device.device_id,
        slot_number=slot.slot_number,
        slot_code=slot.slot_code,
        product_id=slot.product_id,
        product_name=slot.product.name,
        product_code=slot.product.product_code,
        amount_paise=resolved_price_paise,
        amount_rupees=amount_rupees,
        currency="INR",
        qr_payload=upi_uri,
        qr_image_data=None,
        qr_ascii_preview=ascii_preview,
        order_status=order.order_status,
        payment_status=payment.payment_status,
        timeout_seconds=timeout_sec,
        expires_at=expires_at,
        created_at=order.created_at,
    )


def get_order_detail(db: Session, order_id_or_number: str) -> OrderDetailResponse:
    """
    Retrieve real-time status of a purchase order.
    Automatically checks and transitions expired orders.
    """
    order = db.query(Order).filter(
        (Order.id == order_id_or_number) | (Order.order_number == order_id_or_number)
    ).first()
    if not order:
        raise NotFoundException("Order", order_id_or_number)

    # Dynamic Expiration Transition: PENDING orders past expires_at become EXPIRED
    now = utc_now()
    exp = _ensure_utc(order.expires_at)
    if order.order_status in ["PENDING", "PAYMENT_PENDING"] and exp and exp < now:
        order.order_status = "EXPIRED"
        if order.payment and order.payment.payment_status in ["INITIATED", "PENDING"]:
            order.payment.payment_status = "FAILED"
        db.commit()

    seconds_remaining = 0
    if exp and order.order_status in ["PENDING", "PAYMENT_PENDING"]:
        delta = (exp - now).total_seconds()
        seconds_remaining = max(0, int(delta))

    upi_payload = None
    if order.payment and order.payment.raw_gateway_response:
        upi_payload = order.payment.raw_gateway_response.get("upi_uri")

    return OrderDetailResponse(
        order_id=order.id,
        order_number=order.order_number,
        device_id=order.device.device_id if order.device else "UNKNOWN",
        slot_number=order.slot.slot_number if order.slot else 0,
        product_name=order.product.name if order.product else "UNKNOWN",
        product_code=order.product.product_code if order.product else "UNKNOWN",
        amount_paise=order.total_amount,
        amount_rupees=round(order.total_amount / 100.0, 2),
        currency="INR",
        order_status=order.order_status,
        payment_method=order.payment_method,
        payment_status=order.payment.payment_status if order.payment else None,
        gateway_provider=order.payment.gateway_provider if order.payment else None,
        qr_payload=upi_payload,
        expires_at=order.expires_at,
        seconds_remaining=seconds_remaining,
        dispensed_at=order.dispensed_at,
        created_at=order.created_at,
    )


def cancel_order(
    db: Session,
    order_id_or_number: str,
    reason: str = "USER_CANCELLED",
    user_id: Optional[str] = None,
) -> OrderCancelResponse:
    """
    Cancel an active pending dynamic QR order.
    """
    order = db.query(Order).filter(
        (Order.id == order_id_or_number) | (Order.order_number == order_id_or_number)
    ).first()
    if not order:
        raise NotFoundException("Order", order_id_or_number)

    if order.order_status == "CANCELLED":
        return OrderCancelResponse(
            order_id=order.id,
            order_number=order.order_number,
            order_status="CANCELLED",
            cancelled_at=order.updated_at or utc_now(),
            message="Order is already cancelled.",
        )

    if order.order_status in ["PAID", "DISPENSE_AUTHORIZED", "DISPENSED"]:
        raise ConflictException(
            f"Cannot cancel order '{order.order_number}': already in state '{order.order_status}'."
        )

    now = utc_now()
    order.order_status = "CANCELLED"
    if order.payment:
        order.payment.payment_status = "FAILED"

    db.add(AuditLog(
        client_id=order.client_id,
        user_id=user_id,
        action="ORDER_CANCELLED",
        entity_type="ORDER",
        entity_id=order.id,
        old_state={"order_status": "PENDING"},
        new_state={"order_status": "CANCELLED", "reason": reason},
    ))

    db.commit()

    return OrderCancelResponse(
        order_id=order.id,
        order_number=order.order_number,
        order_status="CANCELLED",
        cancelled_at=now,
        message=f"Order successfully cancelled ({reason}).",
    )


def list_orders(
    db: Session,
    client_id: Optional[str] = None,
    device_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    limit: int = 50,
) -> List[OrderDetailResponse]:
    """
    List recent purchase orders, with optional device and status filters.
    Enforces multi-tenant data boundaries.
    """
    query = db.query(Order)
    if client_id:
        query = query.filter(Order.client_id == client_id)
    if device_id:
        query = query.join(Device).filter(Device.device_id == device_id)
    if status_filter:
        query = query.filter(Order.order_status == status_filter.upper())

    orders = query.order_by(Order.created_at.desc()).limit(limit).all()

    now = utc_now()
    results: List[OrderDetailResponse] = []
    for order in orders:
        exp = _ensure_utc(order.expires_at)
        if order.order_status in ["PENDING", "PAYMENT_PENDING"] and exp and exp < now:
            order.order_status = "EXPIRED"
            if order.payment and order.payment.payment_status in ["INITIATED", "PENDING"]:
                order.payment.payment_status = "FAILED"
            db.commit()

        seconds_remaining = 0
        if exp and order.order_status in ["PENDING", "PAYMENT_PENDING"]:
            seconds_remaining = max(0, int((exp - now).total_seconds()))

        upi_payload = None
        if order.payment and order.payment.raw_gateway_response:
            upi_payload = order.payment.raw_gateway_response.get("upi_uri")

        results.append(OrderDetailResponse(
            order_id=order.id,
            order_number=order.order_number,
            device_id=order.device.device_id if order.device else "UNKNOWN",
            slot_number=order.slot.slot_number if order.slot else 0,
            product_name=order.product.name if order.product else "UNKNOWN",
            product_code=order.product.product_code if order.product else "UNKNOWN",
            amount_paise=order.total_amount,
            amount_rupees=round(order.total_amount / 100.0, 2),
            currency="INR",
            order_status=order.order_status,
            payment_method=order.payment_method,
            payment_status=order.payment.payment_status if order.payment else None,
            gateway_provider=order.payment.gateway_provider if order.payment else None,
            qr_payload=upi_payload,
            expires_at=order.expires_at,
            seconds_remaining=seconds_remaining,
            dispensed_at=order.dispensed_at,
            created_at=order.created_at,
        ))

    return results


def mark_order_paid(
    db: Session,
    order_id_or_number: str,
    gateway_txn_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> OrderDetailResponse:
    """
    Transition a dynamic QR order to PAID upon receiving payment confirmation.
    Signals the ESP32 vending machine that payment is complete and it may dispense.
    """
    order = db.query(Order).filter(
        (Order.id == order_id_or_number) | (Order.order_number == order_id_or_number)
    ).first()
    if not order:
        raise NotFoundException("Order", order_id_or_number)

    if order.order_status in ["PAID", "DISPENSE_AUTHORIZED", "DISPENSED"]:
        return get_order_detail(db, order.id)

    order.order_status = "PAID"
    order.paid_at = utc_now()
    if order.payment:
        order.payment.payment_status = "SUCCESS"
        if gateway_txn_id:
            order.payment.gateway_payment_intent_id = gateway_txn_id

    db.add(AuditLog(
        client_id=order.client_id,
        user_id=user_id,
        action="PAYMENT_RECEIVED",
        entity_type="ORDER",
        entity_id=order.id,
        old_state={"order_status": "PENDING"},
        new_state={"order_status": "PAID", "paid_at": str(order.paid_at)},
    ))
    db.commit()
    return get_order_detail(db, order.id)


def mark_order_dispensed(
    db: Session,
    order_id_or_number: str,
    dispense_token: Optional[str] = None,
) -> OrderDetailResponse:
    """
    Called by ESP32 once physical product dispense is confirmed.
    Validates single-use dispense_token, transitions order to DISPENSED,
    and safely decrements machine slot inventory (idempotent: prevents duplicate motor/stock cycles).
    """
    order = db.query(Order).filter(
        (Order.id == order_id_or_number) | (Order.order_number == order_id_or_number)
    ).first()
    if not order:
        raise NotFoundException("Order", order_id_or_number)

    # Idempotency check: If already dispensed, return order detail without double decrementing stock
    if order.order_status == "DISPENSED":
        return get_order_detail(db, order.id)

    # Validate single-use dispense token if provided and active on the order
    if dispense_token and order.dispense_token and order.dispense_token != dispense_token:
        raise BadRequestException("Invalid dispense authorization token.")

    # Consume one-time authorization token immediately
    order.dispense_token = None
    order.order_status = "DISPENSED"
    order.dispensed_at = utc_now()

    # Decrement stock in slot
    if order.slot and order.slot.current_stock > 0:
        order.slot.current_stock -= 1

    db.add(AuditLog(
        client_id=order.client_id,
        user_id=None,
        action="ORDER_DISPENSED",
        entity_type="ORDER",
        entity_id=order.id,
        old_state={"order_status": "PAID"},
        new_state={
            "order_status": "DISPENSED",
            "order_number": order.order_number,
            "device_id": order.device.device_id if order.device else None,
            "slot_number": order.slot.slot_number if order.slot else 1,
            "dispensed_at": str(order.dispensed_at),
        },
    ))
    db.commit()
    return get_order_detail(db, order.id)


def get_pending_dispense_for_device(
    db: Session,
    device_id: str,
    device_token: Optional[str] = None,
) -> Dict[str, Any]:
    """
    [Edge Hardware Polling Endpoint - Buttonless Zero-Touch Vending]
    Checks if an incoming Razorpay payment matched a product price and authorized
    physical motor dispense for this specific machine.
    Enforces strict machine isolation, authenticated sessions, and offline expiry recovery.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.mac_address.ilike(device_id.strip()))
    ).first()
    if not device:
        from src.db.models.client import Client
        from src.db.models.device import DeviceType
        client = db.query(Client).first()
        dev_type = db.query(DeviceType).filter_by(code="VENDING_MACHINE").first()
        if client and dev_type:
            device = Device(
                device_id=device_id,
                client_id=client.id,
                device_type_id=dev_type.id,
                hardware_id=f"HW-{device_id}",
                chip_id=f"CHIP-{device_id}",
                mac_address="AUTO",
                factory_serial=f"SN-{device_id}",
                status="ACTIVE",
                is_online=True,
                last_heartbeat_at=utc_now(),
                current_firmware_version="v2.0.0-razorpay",
                current_config_version=1,
            )
            db.add(device)
            db.commit()
            db.refresh(device)
        else:
            return {"dispense_pending": False}
    else:
        device.is_online = True
        device.last_heartbeat_at = utc_now()
        db.commit()

    now = utc_now()

    # Strict Machine Isolation (Requirement 12): Query ONLY orders belonging to device.id
    pending_orders = (
        db.query(Order)
        .filter(
            Order.device_id == device.id,
            Order.order_status.in_(["PAID", "DISPENSE_AUTHORIZED"]),
        )
        .order_by(Order.paid_at.asc(), Order.created_at.asc())
        .all()
    )

    if not pending_orders:
        return {"dispense_pending": False}

    # Requirement 14: Offline machine retention and expiry policy
    valid_order = None
    for ord in pending_orders:
        exp_utc = _ensure_utc(ord.dispense_token_expires_at)
        if exp_utc and exp_utc < now:
            # Expired while machine was offline. Do not silently lose; mark EXPIRED and audit log.
            ord.order_status = "EXPIRED"
            db.add(AuditLog(
                client_id=ord.client_id,
                user_id=None,
                action="ORDER_DISPENSE_EXPIRED_OFFLINE",
                entity_type="ORDER",
                entity_id=ord.id,
                old_state={"order_status": "PAID"},
                new_state={"order_status": "EXPIRED", "expired_at": str(now)},
            ))
            db.commit()
        else:
            valid_order = ord
            break

    if not valid_order:
        return {"dispense_pending": False}

    # Ensure dispense_token exists
    if not valid_order.dispense_token:
        valid_order.dispense_token = f"auth_{generate_uuid()}"
        hold_minutes = getattr(settings, "OFFLINE_DISPENSE_HOLD_MINUTES", 60)
        valid_order.dispense_token_expires_at = now + timedelta(minutes=hold_minutes)
        db.commit()

    token_exp_utc = _ensure_utc(valid_order.dispense_token_expires_at)
    expires_in_secs = (
        int((token_exp_utc - now).total_seconds())
        if token_exp_utc
        else 3600
    )

    return {
        "dispense_pending": True,
        "order_id": valid_order.id,
        "order_number": valid_order.order_number,
        "dispense_token": valid_order.dispense_token,
        "slot_number": valid_order.slot.slot_number if valid_order.slot else 1,
        "amount_rupees": round(valid_order.total_amount / 100.0, 2),
        "product_name": valid_order.product.name if valid_order.product else "Vending Item",
        "display_title": "PAYMENT SUCCESSFUL",
        "expires_in_seconds": max(0, expires_in_secs),
    }


def process_razorpay_webhook(db: Session, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process incoming Razorpay Webhook for 1000+ machine fleet:
    1. Extracts payment.entity
    2. Identifies target device_id from notes
    3. Matches price (amount in paise) to physical machine slot (e.g. 1000 paise -> Slot 1)
    4. Triggers Razorpay Route transfer to Vendor/Client Linked Account
    5. Sets order state to DISPENSE_AUTHORIZED so ESP32 executes motor dispense.
    """
    event = webhook_data.get("event")
    if event != "payment.captured":
        return {"status": "IGNORED", "reason": f"Unhandled event {event}"}

    payment_entity = webhook_data.get("payload", {}).get("payment", {}).get("entity", {})
    payment_id = payment_entity.get("id")
    amount_paise = payment_entity.get("amount", 0)
    notes = payment_entity.get("notes", {})
    device_id = notes.get("device_id")

    if not device_id:
        return {"status": "IGNORED", "reason": "No device_id in notes"}

    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        return {"status": "ERROR", "reason": f"Device '{device_id}' not found"}

    # Dynamic Price Matching: Match incoming amount to configured slot price
    slot = None
    for s in device.slots:
        if not s.is_active:
            continue
        slot_price = s.override_price if s.override_price is not None else (s.product.price if s.product else None)
        if slot_price == amount_paise:
            slot = s
            break

    # Fallback to Slot 1 (e.g., in single-motor configuration)
    if not slot and device.slots:
        slot = device.slots[0]

    now = utc_now()
    order_id = str(uuid.uuid4())
    order_number = f"ORD-{now.strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

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
        order_status="DISPENSE_AUTHORIZED",
        payment_method="RAZORPAY",
    )
    db.add(order)

    payment = Payment(
        order_id=order_id,
        client_id=device.client_id,
        gateway_provider="RAZORPAY",
        gateway_payment_intent_id=payment_id,
        gateway_transaction_id=payment_id,
        amount=amount_paise,
        currency="INR",
        payment_status="SUCCESS",
        raw_gateway_response=payment_entity,
        paid_at=now,
    )
    db.add(payment)

    db.add(AuditLog(
        client_id=device.client_id,
        user_id=None,
        action="RAZORPAY_PRICE_MATCH_DISPENSE",
        entity_type="ORDER",
        entity_id=order_id,
        old_state={"payment_id": payment_id},
        new_state={"order_number": order_number, "slot_number": slot.slot_number if slot else 1, "amount_paise": amount_paise},
    ))

    db.commit()

    return {
        "status": "DISPENSE_AUTHORIZED",
        "order_id": order_id,
        "order_number": order_number,
        "device_id": device_id,
        "slot_number": slot.slot_number if slot else 1,
        "amount_rupees": round(amount_paise / 100.0, 2),
    }


def get_device_qr_config(db: Session, device_id: str) -> Dict[str, Any]:
    """
    [Edge & Portal Endpoint]
    Fetch active QR code, VPA, and price configuration for a machine.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.mac_address.ilike(device_id.strip()))
    ).first()
    if not device:
        vpa = f"rzp.vending.{device_id.lower()}@icici"
        return {
            "device_id": device_id,
            "razorpay_upi_vpa": vpa,
            "qr_payload": f"upi://pay?pa={vpa}&pn=IoT%20Vending&am=10.00&cu=INR&tn={device_id}",
            "amount_rupees": 10.0,
            "product_name": "Cold Drink",
            "config_version": 1,
        }

    device.is_online = True
    device.last_heartbeat_at = utc_now()
    db.commit()

    # 1. Inspect DeviceModule QR_PAYMENT config
    from src.db.models.device import DeviceModule
    from src.db.models.vending import RazorpayQRCode

    qr_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="QR_PAYMENT").first()
    mod_cfg = dict(qr_mod.configuration or {}) if qr_mod else {}

    settings = device.config.config_payload.get("settings", {}) if (device.config and device.config.config_payload) else {}

    # Priority: UPI deep-links take highest precedence over web/image URLs!
    candidates = [
        mod_cfg.get("custom_qr_image_url"),
        settings.get("custom_qr_payload"),
        mod_cfg.get("custom_qr_payload"),
    ]
    rzp_rec = db.query(RazorpayQRCode).filter_by(device_id=device.id, status="active").order_by(RazorpayQRCode.updated_at.desc()).first()
    if rzp_rec and rzp_rec.qr_payload:
        candidates.append(rzp_rec.qr_payload)

    custom_qr = None
    # Prefer candidates that start with valid UPI protocol (upi://)
    for c in candidates:
        if c and isinstance(c, str) and c.strip().startswith("upi://"):
            custom_qr = c.strip()
            break
    # Fallback to any candidate
    if not custom_qr:
        for c in candidates:
            if c and isinstance(c, str) and len(c.strip()) > 0:
                custom_qr = c.strip()
                break

    vpa = (
        settings.get("razorpay_upi_vpa")
        or mod_cfg.get("upi_merchant_vpa")
        or f"rzp.vending.{device.device_id.lower()}@icici"
    )
    if custom_qr and custom_qr.startswith("upi://pay"):
        try:
            parsed = urllib.parse.urlparse(custom_qr)
            qs = urllib.parse.parse_qs(parsed.query)
            if "pa" in qs and qs["pa"][0]:
                vpa = qs["pa"][0]
        except Exception:
            pass

    # Ensure device.config is synchronized with resolved UPI QR & VPA
    if custom_qr and device.config and device.config.config_payload:
        cfg_payload = dict(device.config.config_payload)
        if "settings" not in cfg_payload:
            cfg_payload["settings"] = {}
        if cfg_payload["settings"].get("custom_qr_payload") != custom_qr:
            from sqlalchemy.orm.attributes import flag_modified
            cfg_payload["settings"]["custom_qr_payload"] = custom_qr
            cfg_payload["settings"]["razorpay_upi_vpa"] = vpa
            device.config.config_payload = cfg_payload
            flag_modified(device.config, "config_payload")
            db.commit()

    slot = device.slots[0] if device.slots else None
    price_paise = slot.override_price if (slot and slot.override_price is not None) else (slot.product.price if (slot and slot.product) else 1000)
    amount_rupees = round(price_paise / 100.0, 2)
    product_name = slot.product.name if (slot and slot.product) else "Cold Drink"

    if custom_qr and not custom_qr.startswith("data:image/") and not custom_qr.startswith("http://") and not custom_qr.startswith("https://"):
        qr_payload = custom_qr
    elif custom_qr and (custom_qr.startswith("data:image/") or "base64," in custom_qr):
        from src.services.vending_service import decode_qr_image_data
        decoded = decode_qr_image_data(custom_qr)
        if decoded and decoded.get("qr_payload"):
            qr_payload = decoded["qr_payload"]
        else:
            qr_payload = f"upi://pay?pa={vpa}&pn=IoT%20Vending&am={amount_rupees:.2f}&cu=INR&tn={device.device_id}"
    else:
        qr_payload = f"upi://pay?pa={vpa}&pn=IoT%20Vending&am={amount_rupees:.2f}&cu=INR&tn={device.device_id}"

    return {
        "device_id": device.device_id,
        "razorpay_upi_vpa": vpa,
        "qr_payload": qr_payload,
        "amount_rupees": amount_rupees,
        "product_name": product_name,
        "config_version": device.current_config_version,
    }


def update_device_qr_config(db: Session, device_id: str, payload_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    [Vendor / Manufacturer Portal Endpoint]
    Allows vendor or manufacturer to change the QR code, UPI VPA, or item price online.
    Increments config_version so the ESP32 automatically pulls the update and changes its screen.
    """
    device = db.query(Device).filter(
        (Device.device_id == device_id) | (Device.mac_address.ilike(device_id.strip()))
    ).first()
    if not device:
        raise NotFoundException("Device", device_id)

    if not device.config:
        from src.db.models.config import DeviceConfig
        device.config = DeviceConfig(device_id=device.id, config_payload={"settings": {}}, is_synced=False)
        db.add(device.config)

    payload = dict(device.config.config_payload) if device.config.config_payload else {"settings": {}}
    if "settings" not in payload:
        payload["settings"] = {}

    raw_qr = (
        payload_data.get("custom_qr_payload")
        or payload_data.get("qr_payload")
        or payload_data.get("upi_url")
        or payload_data.get("qr_string")
    )

    # Intelligent UPI URI parsing (e.g. upi://pay?am=2.00&cu=INR&pa=...&tr=...)
    if raw_qr:
        raw_qr = str(raw_qr).strip()
        if raw_qr.startswith("data:image/") or "base64," in raw_qr:
            from src.services.vending_service import decode_qr_image_data
            decoded = decode_qr_image_data(raw_qr)
            if decoded and decoded.get("qr_payload"):
                raw_qr = decoded["qr_payload"]
                if decoded.get("vpa") and not payload_data.get("razorpay_upi_vpa"):
                    payload_data["razorpay_upi_vpa"] = decoded["vpa"]
                if decoded.get("amount_rupees") is not None and "amount_rupees" not in payload_data:
                    payload_data["amount_rupees"] = decoded["amount_rupees"]
        payload["settings"]["custom_qr_payload"] = raw_qr

        if raw_qr.startswith("upi://pay"):
            try:
                parsed = urllib.parse.urlparse(raw_qr)
                qs = urllib.parse.parse_qs(parsed.query)

                # Extract UPI VPA (pa)
                if "pa" in qs and qs["pa"][0]:
                    vpa_val = qs["pa"][0]
                    payload["settings"]["razorpay_upi_vpa"] = vpa_val
                    payload_data["razorpay_upi_vpa"] = vpa_val

                # Extract Amount (am)
                if "am" in qs and qs["am"][0]:
                    try:
                        amt_val = float(qs["am"][0])
                        payload_data["amount_rupees"] = amt_val
                    except ValueError:
                        pass

                # Extract Transaction Reference / QR ID (tr)
                tr_val = qs.get("tr", [None])[0]
                if tr_val:
                    from src.db.models.vending import RazorpayQRCode
                    amt_paise = int(payload_data.get("amount_rupees", 2.0) * 100)
                    existing_qr = db.query(RazorpayQRCode).filter(RazorpayQRCode.razorpay_qr_id == tr_val).first()
                    if not existing_qr:
                        qr_rec = RazorpayQRCode(
                            client_id=device.client_id,
                            device_id=device.id,
                            slot_id=device.slots[0].id if device.slots else None,
                            razorpay_qr_id=tr_val,
                            name=f"Standee QR {tr_val}",
                            usage="multiple_use",
                            fixed_amount=True,
                            amount=amt_paise,
                            currency="INR",
                            qr_payload=raw_qr,
                            status="active",
                            notes={"device_id": device.device_id, "tr": tr_val},
                        )
                        db.add(qr_rec)
                    else:
                        existing_qr.device_id = device.id
                        existing_qr.amount = amt_paise
                        existing_qr.qr_payload = raw_qr
                        existing_qr.status = "active"
            except Exception:
                pass

    if payload_data.get("razorpay_upi_vpa"):
        payload["settings"]["razorpay_upi_vpa"] = payload_data["razorpay_upi_vpa"]
    if payload_data.get("amount_rupees") is not None:
        amount_paise = int(payload_data["amount_rupees"] * 100)
        if device.slots:
            device.slots[0].override_price = amount_paise
    if payload_data.get("product_name") and device.slots:
        prod_name = payload_data["product_name"].strip()
        if device.slots[0].product:
            device.slots[0].product.name = prod_name
        else:
            from src.db.models.vending import Product
            prod_code = f"PROD-{device.device_id}-1"
            prod = db.query(Product).filter_by(client_id=device.client_id, product_code=prod_code).first()
            if not prod:
                from src.db.base import generate_uuid
                prod = Product(
                    id=generate_uuid(),
                    client_id=device.client_id,
                    name=prod_name,
                    product_code=prod_code,
                    price=int(payload_data.get("amount_rupees", 10.0) * 100),
                    is_active=True,
                )
                db.add(prod)
                db.flush()
            else:
                prod.name = prod_name
            device.slots[0].product_id = prod.id

    # Synchronize DeviceModule for QR_PAYMENT
    from src.db.models.device import DeviceModule
    qr_mod = db.query(DeviceModule).filter_by(device_id=device.id, module_code="QR_PAYMENT").first()
    if qr_mod:
        mod_cfg = dict(qr_mod.configuration or {})
        if raw_qr:
            mod_cfg["custom_qr_image_url"] = raw_qr
        if payload_data.get("razorpay_upi_vpa"):
            mod_cfg["upi_merchant_vpa"] = payload_data["razorpay_upi_vpa"]
        qr_mod.configuration = mod_cfg

    from sqlalchemy.orm.attributes import flag_modified
    device.config.config_payload = dict(payload)
    flag_modified(device.config, "config_payload")
    device.config.is_synced = False
    device.current_config_version += 1
    device.config.active_version = device.current_config_version

    db.add(AuditLog(
        client_id=device.client_id,
        user_id=None,
        action="QR_CONFIG_UPDATED",
        entity_type="DEVICE",
        entity_id=device.id,
        old_state={},
        new_state=payload_data,
    ))

    db.commit()
    return get_device_qr_config(db, device_id)


