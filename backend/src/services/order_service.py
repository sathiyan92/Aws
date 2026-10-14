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
from src.db.base import utc_now
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
) -> OrderDetailResponse:
    """
    Called by ESP32 once physical product dispense is finished.
    Transitions order to DISPENSED and decrements machine slot inventory.
    """
    order = db.query(Order).filter(
        (Order.id == order_id_or_number) | (Order.order_number == order_id_or_number)
    ).first()
    if not order:
        raise NotFoundException("Order", order_id_or_number)

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
        new_state={"order_status": "DISPENSED", "dispensed_at": str(order.dispensed_at)},
    ))
    db.commit()
    return get_order_detail(db, order.id)
