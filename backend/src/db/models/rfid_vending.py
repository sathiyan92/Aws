"""
RFID Card Vending Machine Models.
Supports high-scale (1000+ users/cards per machine) mapping, daily vend limits,
bulk uploads, live tap enrollment, and calendar-filtered audit reporting.
"""
from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, ForeignKey, Index, Text
from sqlalchemy.orm import relationship
from src.db.base import Base, generate_uuid, utc_now


class RFIDVendingCard(Base):
    """
    Authorized RFID Card mapped to a specific machine or client tenant.
    Designed for fast indexed lookups (< 2ms) and 1000+ cards per machine.
    """
    __tablename__ = "rfid_vending_cards"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    client_id = Column(String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String(36), ForeignKey("devices.id", ondelete="SET NULL"), nullable=True, index=True)
    card_uid = Column(String(64), nullable=False, index=True)
    username = Column(String(128), nullable=False, default="Cardholder")
    department = Column(String(128), nullable=True)
    daily_limit = Column(Integer, default=1, nullable=False)  # Max dispenses per day (0 or -1 = unlimited)
    used_today = Column(Integer, default=0, nullable=False)
    last_vended_at = Column(DateTime, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    notes = Column(String(256), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    # Relationships
    client = relationship("Client", foreign_keys=[client_id])
    device = relationship("Device", foreign_keys=[device_id])

    __table_args__ = (
        Index("idx_rfid_vending_lookup", "client_id", "device_id", "card_uid"),
        Index("idx_rfid_card_uid_active", "card_uid", "is_active"),
    )


class RFIDVendingLog(Base):
    """
    Audit and telemetry log for every RFID card tap, vend attempt, and dispense event.
    Queried for calendar, vendor, and machine-filtered Excel/CSV reporting.
    """
    __tablename__ = "rfid_vending_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime, default=utc_now, nullable=False, index=True)
    client_id = Column(String(36), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True)
    device_id = Column(String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False, index=True)
    card_uid = Column(String(64), nullable=False, index=True)
    username = Column(String(128), nullable=False, default="Cardholder")
    department = Column(String(128), nullable=True)
    status = Column(String(64), nullable=False, default="DISPENSED_SUCCESS", index=True)
    pulse_duration_ms = Column(Integer, default=1500, nullable=False)
    notes = Column(Text, nullable=True)

    # Relationships
    client = relationship("Client", foreign_keys=[client_id])
    device = relationship("Device", foreign_keys=[device_id])

    __table_args__ = (
        Index("idx_rfid_log_filter", "client_id", "device_id", "timestamp"),
        Index("idx_rfid_log_status", "status", "timestamp"),
    )

