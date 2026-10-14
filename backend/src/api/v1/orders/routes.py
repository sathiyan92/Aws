"""
Order API Router.
Provides transaction-based dynamic QR payment intent endpoints:
initiation, real-time polling, cancellation, and tenant-scoped order history.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, Request, status
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
    db: Session = Depends(get_db),
):
    """
    [Edge Hardware Callback Endpoint]
    Called by ESP32 once physical product dispense is confirmed (e.g., motor cycle complete).
    Transitions order to DISPENSED and decrements machine slot inventory.
    """
    return mark_order_dispensed(db=db, order_id_or_number=order_id)


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
