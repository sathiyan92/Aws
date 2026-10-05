"""
Audit logging model for tracking immutable administrative, configuration, and security operations.
"""
from datetime import datetime
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import String, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, generate_uuid, utc_now

if TYPE_CHECKING:
    from src.db.models.client import Client
    from src.db.models.user import User


class AuditLog(Base):
    """
    Immutable audit log entry recording who performed what action on which entity and when.
    """
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )  # PRICE_CHANGE, MODULE_TOGGLE, OTA_TRIGGER, CARD_STATUS_CHANGE, DEVICE_ASSIGN
    entity_type: Mapped[str] = mapped_column(
        String(64),
        index=True,
        nullable=False,
    )  # DEVICE, PRODUCT, RFID_CARD, CONFIG, FIRMWARE
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    old_state: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    new_state: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )

    # Relationships
    client: Mapped[Optional["Client"]] = relationship("Client", back_populates="audit_logs")
    user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("idx_audit_client_created", "client_id", "created_at"),
        Index("idx_audit_entity", "entity_type", "entity_id"),
    )

    def __repr__(self) -> str:
        return f"<AuditLog(action='{self.action}', entity='{self.entity_type}:{self.entity_id}', user='{self.user_id}')>"
