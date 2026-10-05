"""
Edge telemetry models: Device Heartbeats and Diagnostic Logs.
"""
from datetime import datetime
from typing import Optional, Any, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, generate_uuid, utc_now

if TYPE_CHECKING:
    from src.db.models.device import Device
    from src.db.models.client import Client


class DeviceHeartbeat(Base):
    """
    Time-series snapshot of device operational metrics reported during periodic heartbeats.
    """
    __tablename__ = "device_heartbeats"

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
    status: Mapped[str] = mapped_column(String(32), default="ONLINE", nullable=False)
    current_firmware_version: Mapped[str] = mapped_column(String(32), nullable=False)
    current_config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    uptime_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    free_heap_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    wifi_rssi: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    active_errors: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )

    # Relationships
    device: Mapped["Device"] = relationship("Device", back_populates="heartbeats")

    __table_args__ = (
        Index("idx_heartbeat_device_recorded", "device_id", "recorded_at"),
    )

    def __repr__(self) -> str:
        return f"<DeviceHeartbeat(device_id='{self.device_id}', status='{self.status}', time='{self.recorded_at}')>"


class DeviceLog(Base):
    """
    Diagnostic, system, and hardware event logs reported by edge nodes.
    """
    __tablename__ = "device_logs"

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
    log_level: Mapped[str] = mapped_column(
        String(16),
        index=True,
        nullable=False,
    )  # DEBUG, INFO, WARN, ERROR, FATAL
    subsystem: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
    )  # CORE, NET, CONFIG, COIN, QR, RFID, OTA, DROP_SENSOR
    message: Mapped[str] = mapped_column(Text, nullable=False)
    log_data: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
        nullable=False,
    )

    # Relationships
    device: Mapped["Device"] = relationship("Device", back_populates="logs")

    __table_args__ = (
        Index("idx_device_logs_device_time", "device_id", "recorded_at"),
        Index("idx_device_logs_level_time", "log_level", "recorded_at"),
    )

    def __repr__(self) -> str:
        return f"<DeviceLog(device_id='{self.device_id}', level='{self.log_level}', sub='{self.subsystem}')>"
