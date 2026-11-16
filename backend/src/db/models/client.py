"""
Client (Tenant) entity model representing companies/organizations leasing or owning devices.
"""
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, DateTime, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from src.db.models.user import User
    from src.db.models.device import Device
    from src.db.models.vending import Product, MachineSlot, Order, Transaction, PayoutTransfer
    from src.db.models.rfid import Employee, RFIDCard, AttendanceEvent
    from src.db.models.audit import AuditLog


class Client(Base, TimestampMixin):
    """
    Client / Tenant organization.
    All non-manufacturer data in the system belongs to exactly one Client.
    """
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    client_code: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True, nullable=False)  # ACTIVE, SUSPENDED, INACTIVE
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Razorpay Route & Settlement Details
    bank_account_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    bank_ifsc: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    bank_beneficiary_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    commission_percentage: Mapped[float] = mapped_column(Float, default=10.0, nullable=False)  # Platform fee %, e.g., 10.0%
    razorpay_account_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)  # Razorpay Route Linked Account ID: acc_...
    razorpay_merchant_vpa: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)  # Direct vendor UPI ID
    payout_status: Mapped[str] = mapped_column(String(32), default="UNLINKED", nullable=False)  # UNLINKED, ACTIVE, SUSPENDED

    # Relationships
    users: Mapped[List["User"]] = relationship("User", back_populates="client", cascade="all, delete-orphan")
    devices: Mapped[List["Device"]] = relationship("Device", back_populates="client")
    products: Mapped[List["Product"]] = relationship("Product", back_populates="client", cascade="all, delete-orphan")
    employees: Mapped[List["Employee"]] = relationship("Employee", back_populates="client", cascade="all, delete-orphan")
    rfid_cards: Mapped[List["RFIDCard"]] = relationship("RFIDCard", back_populates="client", cascade="all, delete-orphan")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="client")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="client")
    payout_transfers: Mapped[List["PayoutTransfer"]] = relationship("PayoutTransfer", back_populates="client")
    audit_logs: Mapped[List["AuditLog"]] = relationship("AuditLog", back_populates="client")

    def __repr__(self) -> str:
        return f"<Client(id={self.id}, code='{self.client_code}', name='{self.name}', status='{self.status}')>"
