"""
Vending machine subsystem models: Products, Slots, Orders, Payments, and Transactions.
"""
from datetime import datetime
from typing import List, Optional, Any, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, Boolean, DateTime, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin, generate_uuid, utc_now

if TYPE_CHECKING:
    from src.db.models.client import Client
    from src.db.models.device import Device


class Product(Base, TimestampMixin):
    """
    Catalog product entity owned by a Client tenant.
    Prices are represented in smallest currency unit (e.g., paise: 4000 = ₹40.00).
    """
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[int] = mapped_column(Integer, nullable=False)  # In paise / cents
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    client: Mapped["Client"] = relationship("Client", back_populates="products")
    slots: Mapped[List["MachineSlot"]] = relationship("MachineSlot", back_populates="product")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="product")

    __table_args__ = (
        UniqueConstraint("client_id", "product_code", name="uq_client_product_code"),
        Index("idx_products_client_active", "client_id", "is_active"),
    )

    def __repr__(self) -> str:
        return f"<Product(code='{self.product_code}', name='{self.name}', price={self.price})>"


class MachineSlot(Base, TimestampMixin):
    """
    Physical dispensing slot on a vending machine.
    """
    __tablename__ = "machine_slots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)  # 1, 2, 3...
    slot_code: Mapped[str] = mapped_column(String(32), nullable=False)  # SLOT-01
    product_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    override_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    capacity: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    current_stock: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    motor_pin: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # Hardware GPIO / relay pin index
    pulse_duration_ms: Mapped[int] = mapped_column(Integer, default=500, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Relationships
    device: Mapped["Device"] = relationship("Device", back_populates="slots")
    product: Mapped[Optional["Product"]] = relationship("Product", back_populates="slots")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="slot")

    __table_args__ = (
        UniqueConstraint("device_id", "slot_number", name="uq_device_slot_number"),
        Index("idx_slots_client_device", "client_id", "device_id"),
    )

    def __repr__(self) -> str:
        return f"<MachineSlot(slot='{self.slot_code}', product_id='{self.product_id}', stock={self.current_stock})>"


class Order(Base, TimestampMixin):
    """
    Vending purchase order covering dynamic QR, coin, or RFID dispense requests.
    """
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    order_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("machine_slots.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payment_method: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )  # QR_PAYMENT, COIN_PAYMENT, RFID_ACCESS
    unit_price: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    order_status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        index=True,
        nullable=False,
    )  # PENDING, PAYMENT_PENDING, PAID, DISPENSE_AUTHORIZED, DISPENSED, FAILED, REFUNDED, CANCELLED, EXPIRED
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dispense_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    dispense_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    dispensed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    razorpay_qr_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    qr_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


    # Relationships
    client: Mapped["Client"] = relationship("Client", back_populates="orders")
    device: Mapped["Device"] = relationship("Device", back_populates="orders")
    slot: Mapped["MachineSlot"] = relationship("MachineSlot", back_populates="orders")
    product: Mapped["Product"] = relationship("Product", back_populates="orders")
    payment: Mapped[Optional["Payment"]] = relationship("Payment", back_populates="order", uselist=False, cascade="all, delete-orphan")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="order")

    __table_args__ = (
        Index("idx_orders_client_created", "client_id", "created_at"),
        Index("idx_orders_device_created", "device_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Order(number='{self.order_number}', status='{self.order_status}', amount={self.total_amount})>"


class Payment(Base, TimestampMixin):
    """
    Payment gateway intent and settlement status.
    """
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    order_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("orders.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    gateway_provider: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )  # UPI_DYNAMIC, RAZORPAY, STRIPE, INTERNAL_COIN
    gateway_payment_intent_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    gateway_transaction_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    gateway_event_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    razorpay_payment_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    razorpay_order_id: Mapped[Optional[str]] = mapped_column(String(128), index=True, nullable=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    payment_status: Mapped[str] = mapped_column(
        String(32),
        default="INITIATED",
        index=True,
        nullable=False,
    )  # INITIATED, PENDING, SUCCESS, FAILED, REFUNDED
    raw_gateway_response: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    order: Mapped["Order"] = relationship("Order", back_populates="payment")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="payment")

    def __repr__(self) -> str:
        return f"<Payment(order_id='{self.order_id}', provider='{self.gateway_provider}', status='{self.payment_status}')>"


class Transaction(Base, TimestampMixin):
    """
    Immutable financial transaction record (supports both digital QR payments and cash/coin collections).
    """
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    transaction_number: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    order_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payment_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("payments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    transaction_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )  # QR_VEND, COIN_VEND, COIN_REFUND, GATEWAY_REFUND
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    coins_inserted: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # e.g., {"10": 3} for ₹30 in ₹10 coins
    change_dispensed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    dispense_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
    )  # SUCCESS, FAILURE, JAMMED
    is_offline_sync: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    transacted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)

    # Relationships
    client: Mapped["Client"] = relationship("Client", back_populates="transactions")
    device: Mapped["Device"] = relationship("Device", back_populates="transactions")
    order: Mapped[Optional["Order"]] = relationship("Order", back_populates="transactions")
    payment: Mapped[Optional["Payment"]] = relationship("Payment", back_populates="transactions")

    __table_args__ = (
        Index("idx_transactions_client_time", "client_id", "transacted_at"),
        Index("idx_transactions_device_time", "device_id", "transacted_at"),
    )

    def __repr__(self) -> str:
        return f"<Transaction(num='{self.transaction_number}', type='{self.transaction_type}', amount={self.amount})>"


class WebhookEvent(Base, TimestampMixin):
    """
    Audit log and idempotency guard for incoming payment gateway webhooks.
    Guarantees at-most-once processing of Razorpay webhook notifications.
    """
    __tablename__ = "webhook_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    event_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    gateway: Mapped[str] = mapped_column(String(32), default="RAZORPAY", nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="RECEIVED",
        index=True,
        nullable=False,
    )  # RECEIVED, PROCESSED, DUPLICATE_IGNORED, FAILED
    payload: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_webhook_events_gateway_status", "gateway", "status"),
    )

    def __repr__(self) -> str:
        return f"<WebhookEvent(id='{self.event_id}', type='{self.event_type}', status='{self.status}')>"


class RazorpayQRCode(Base, TimestampMixin):
    """
    Persistent record of Razorpay QR codes generated for devices or slots.
    Supports both dynamic (order-specific) and static UPI QR codes.
    """
    __tablename__ = "razorpay_qr_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("machine_slots.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    razorpay_qr_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    usage: Mapped[str] = mapped_column(String(32), default="single_use", nullable=False)  # single_use, multiple_use
    fixed_amount: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # In paise
    currency: Mapped[str] = mapped_column(String(8), default="INR", nullable=False)
    qr_payload: Mapped[str] = mapped_column(Text, nullable=False)  # UPI URI string
    image_url: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)  # active, closed, expired
    notes: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    client: Mapped["Client"] = relationship("Client")
    device: Mapped["Device"] = relationship("Device")
    slot: Mapped[Optional["MachineSlot"]] = relationship("MachineSlot")

    __table_args__ = (
        Index("idx_razorpay_qr_device_status", "device_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<RazorpayQRCode(qr_id='{self.razorpay_qr_id}', device_id='{self.device_id}', amount={self.amount})>"

