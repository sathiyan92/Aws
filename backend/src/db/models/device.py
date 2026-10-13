"""
Device, DeviceType, DeviceModule, and DeviceCredential entity models.
Enforces physical device identity, module configurability, and secure authentication.
"""
from datetime import datetime
from typing import List, Optional, Any, TYPE_CHECKING
from sqlalchemy import String, Text, Boolean, Integer, DateTime, JSON, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from src.db.models.client import Client
    from src.db.models.config import DeviceConfig, ConfigurationVersion
    from src.db.models.vending import MachineSlot, Order, Transaction
    from src.db.models.rfid import AttendanceEvent
    from src.db.models.firmware import OTADeployment
    from src.db.models.telemetry import DeviceHeartbeat, DeviceLog


class DeviceType(Base, TimestampMixin):
    """
    Extensible registry of hardware product types (e.g., VENDING_MACHINE, RFID_ATTENDANCE).
    """
    __tablename__ = "device_types"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)  # VENDING_MACHINE, RFID_ATTENDANCE
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    supported_modules: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # List of supported module codes
    capability_schema: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # JSON Schema for validation

    # Relationships
    devices: Mapped[List["Device"]] = relationship("Device", back_populates="device_type")

    def __repr__(self) -> str:
        return f"<DeviceType(code='{self.code}', name='{self.name}')>"


class Device(Base, TimestampMixin):
    """
    Physical ESP32 device instance with permanent identity, hardware tuple, and operational state.
    """
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    device_id: Mapped[str] = mapped_column(
        String(32),
        unique=True,
        index=True,
        nullable=False,
    )  # Permanent ID: VM-000001, RFID-000001
    client_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    device_type_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("device_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    hardware_id: Mapped[str] = mapped_column(String(64), nullable=False)  # HW-ESP32S3-V1.2
    chip_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)  # eFuse chip ID
    mac_address: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    factory_serial: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        default="PROVISIONED",
        index=True,
        nullable=False,
    )  # PROVISIONED, ASSIGNED, ACTIVE, MAINTENANCE, SUSPENDED, DECOMMISSIONED
    is_online: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    current_firmware_version: Mapped[str] = mapped_column(String(32), default="v1.0.0", nullable=False)
    current_config_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    # Relationships
    client: Mapped[Optional["Client"]] = relationship("Client", back_populates="devices")
    device_type: Mapped["DeviceType"] = relationship("DeviceType", back_populates="devices")
    modules: Mapped[List["DeviceModule"]] = relationship("DeviceModule", back_populates="device", cascade="all, delete-orphan")
    credentials: Mapped[Optional["DeviceCredential"]] = relationship("DeviceCredential", back_populates="device", uselist=False, cascade="all, delete-orphan")
    config: Mapped[Optional["DeviceConfig"]] = relationship("DeviceConfig", back_populates="device", uselist=False, cascade="all, delete-orphan")
    config_history: Mapped[List["ConfigurationVersion"]] = relationship("ConfigurationVersion", back_populates="device", cascade="all, delete-orphan")
    slots: Mapped[List["MachineSlot"]] = relationship("MachineSlot", back_populates="device", cascade="all, delete-orphan")
    orders: Mapped[List["Order"]] = relationship("Order", back_populates="device", cascade="all, delete-orphan")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="device", cascade="all, delete-orphan")
    attendance_events: Mapped[List["AttendanceEvent"]] = relationship("AttendanceEvent", back_populates="device", cascade="all, delete-orphan")
    ota_deployments: Mapped[List["OTADeployment"]] = relationship("OTADeployment", back_populates="device", cascade="all, delete-orphan")
    heartbeats: Mapped[List["DeviceHeartbeat"]] = relationship("DeviceHeartbeat", back_populates="device", cascade="all, delete-orphan")
    logs: Mapped[List["DeviceLog"]] = relationship("DeviceLog", back_populates="device", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_devices_client_status", "client_id", "status"),
        Index("idx_devices_chip_mac", "chip_id", "mac_address"),
    )

    def __repr__(self) -> str:
        return f"<Device(device_id='{self.device_id}', status='{self.status}', client_id='{self.client_id}')>"


class DeviceModule(Base, TimestampMixin):
    """
    Subsystem feature flag independently configurable per physical device.
    Examples: QR_PAYMENT, COIN_PAYMENT, RFID_ACCESS.
    """
    __tablename__ = "device_modules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    module_code: Mapped[str] = mapped_column(String(64), nullable=False)  # QR_PAYMENT, COIN_PAYMENT, RFID_ACCESS
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    configuration: Mapped[Optional[Any]] = mapped_column(JSON, nullable=True)  # Module-specific config options

    # Relationship
    device: Mapped["Device"] = relationship("Device", back_populates="modules")

    __table_args__ = (
        UniqueConstraint("device_id", "module_code", name="uq_device_module"),
        Index("idx_device_module_enabled", "device_id", "module_code", "is_enabled"),
    )

    def __repr__(self) -> str:
        return f"<DeviceModule(device_id='{self.device_id}', module='{self.module_code}', enabled={self.is_enabled})>"


class DeviceCredential(Base, TimestampMixin):
    """
    Cryptographic authentication material for an ESP32 hardware node.
    """
    __tablename__ = "device_credentials"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    auth_type: Mapped[str] = mapped_column(String(32), default="TOKEN", nullable=False)  # TOKEN, CERTIFICATE, HMAC_KEY
    token_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_cert_fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    secret_key_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationship
    device: Mapped["Device"] = relationship("Device", back_populates="credentials")

    def __repr__(self) -> str:
        return f"<DeviceCredential(device_id='{self.device_id}', auth_type='{self.auth_type}', revoked={self.is_revoked})>"
