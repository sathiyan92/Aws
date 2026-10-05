"""
Device configuration and version history models.
Supports decoupled pricing/module updates without firmware recompilation.
"""
from datetime import datetime
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import String, Integer, Boolean, DateTime, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from src.db.models.device import Device
    from src.db.models.client import Client
    from src.db.models.user import User


class DeviceConfig(Base, TimestampMixin):
    """
    Active configuration state for a device. Synchronized with the physical node.
    """
    __tablename__ = "device_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    client_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    active_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    config_payload: Mapped[Any] = mapped_column(JSON, nullable=False)  # Full JSON payload
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256
    is_synced: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    device: Mapped["Device"] = relationship("Device", back_populates="config")

    def __repr__(self) -> str:
        return f"<DeviceConfig(device_id='{self.device_id}', version={self.active_version}, synced={self.is_synced})>"


class ConfigurationVersion(Base):
    """
    Immutable historical archive of every configuration version generated for a device.
    Allows point-in-time auditing and rollback.
    """
    __tablename__ = "configuration_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    config_payload: Mapped[Any] = mapped_column(JSON, nullable=False)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    change_reason: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    # Relationships
    device: Mapped["Device"] = relationship("Device", back_populates="config_history")
    created_by_user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        UniqueConstraint("device_id", "version_number", name="uq_device_config_version"),
        Index("idx_config_history_lookup", "device_id", "version_number"),
    )

    def __repr__(self) -> str:
        return f"<ConfigurationVersion(device_id='{self.device_id}', v={self.version_number})>"
