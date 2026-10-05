"""
RFID Attendance Subsystem models: Employees, RFID Cards, and Attendance Events.
Maintains strict referential integrity; historical cards are never hard deleted.
"""
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin, generate_uuid, utc_now

if TYPE_CHECKING:
    from src.db.models.client import Client
    from src.db.models.device import Device


class Employee(Base, TimestampMixin):
    """
    Organization member or student associated with RFID cards and attendance events.
    """
    __tablename__ = "employees"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_code: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., EMP001
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)  # e.g., Arun Kumar
    department: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    designation: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        index=True,
        nullable=False,
    )  # ACTIVE, ON_LEAVE, TERMINATED

    # Relationships
    client: Mapped["Client"] = relationship("Client", back_populates="employees")
    cards: Mapped[List["RFIDCard"]] = relationship("RFIDCard", back_populates="employee")
    attendance_events: Mapped[List["AttendanceEvent"]] = relationship("AttendanceEvent", back_populates="employee")

    __table_args__ = (
        UniqueConstraint("client_id", "employee_code", name="uq_client_employee_code"),
        Index("idx_employees_client_status", "client_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Employee(code='{self.employee_code}', name='{self.full_name}', status='{self.status}')>"


class RFIDCard(Base, TimestampMixin):
    """
    Physical RFID card issued to an employee.
    Lifecycle states: ACTIVE, DISABLED, BLOCKED, REPLACED.
    Cards are never permanently deleted when historical attendance exists.
    """
    __tablename__ = "rfid_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    employee_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    card_uid: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., 04:A3:92:7B:11:65
    status: Mapped[str] = mapped_column(
        String(32),
        default="ACTIVE",
        index=True,
        nullable=False,
    )  # ACTIVE, DISABLED, BLOCKED, REPLACED
    replacement_card_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("rfid_cards.id", ondelete="SET NULL"),
        nullable=True,
    )  # Self-referential pointer for replacement lineage
    issued_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Relationships
    client: Mapped["Client"] = relationship("Client", back_populates="rfid_cards")
    employee: Mapped[Optional["Employee"]] = relationship("Employee", back_populates="cards")
    replacement_card: Mapped[Optional["RFIDCard"]] = relationship("RFIDCard", remote_side=[id])
    attendance_events: Mapped[List["AttendanceEvent"]] = relationship("AttendanceEvent", back_populates="card")

    __table_args__ = (
        UniqueConstraint("client_id", "card_uid", name="uq_client_card_uid"),
        Index("idx_rfid_cards_client_status", "client_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<RFIDCard(uid='{self.card_uid}', status='{self.status}', emp_id='{self.employee_id}')>"


class AttendanceEvent(Base):
    """
    Immutable attendance scan record captured at an RFID terminal.
    Contains edge-generated event_uuid for idempotent deduplication during offline sync.
    """
    __tablename__ = "attendance_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    event_uuid: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )  # Edge idempotency key
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
    card_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("rfid_cards.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    employee_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("employees.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    card_uid_scanned: Mapped[str] = mapped_column(String(64), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True, nullable=False)  # Physical scan time
    event_type: Mapped[str] = mapped_column(String(16), nullable=False)  # IN, OUT, UNKNOWN
    is_offline_sync: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # Relationships
    client: Mapped["Client"] = relationship("Client")
    device: Mapped["Device"] = relationship("Device", back_populates="attendance_events")
    card: Mapped[Optional["RFIDCard"]] = relationship("RFIDCard", back_populates="attendance_events")
    employee: Mapped[Optional["Employee"]] = relationship("Employee", back_populates="attendance_events")

    __table_args__ = (
        Index("idx_attendance_client_time", "client_id", "timestamp"),
        Index("idx_attendance_device_time", "device_id", "timestamp"),
        Index("idx_attendance_employee_time", "employee_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AttendanceEvent(card='{self.card_uid_scanned}', event='{self.event_type}', time='{self.timestamp}')>"
