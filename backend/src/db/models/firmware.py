"""
Firmware repository and Over-The-Air (OTA) deployment tracking models.
"""
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING
from sqlalchemy import String, Text, Integer, Boolean, DateTime, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from src.db.models.device import DeviceType, Device
    from src.db.models.client import Client
    from src.db.models.user import User


class FirmwareVersion(Base, TimestampMixin):
    """
    Firmware binary artifact uploaded and digitally signed by the platform manufacturer.
    """
    __tablename__ = "firmware_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    device_type_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("device_types.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    version_string: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g., v1.0.0
    hardware_revision: Mapped[str] = mapped_column(String(64), nullable=False)  # e.g., HW-ESP32S3-V1.2
    binary_url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256_checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)  # ECDSA-P256 digital signature
    changelog: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_deprecated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    device_type: Mapped["DeviceType"] = relationship("DeviceType")
    deployments: Mapped[List["OTADeployment"]] = relationship("OTADeployment", back_populates="firmware_version")
    created_by_user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        UniqueConstraint("device_type_id", "version_string", "hardware_revision", name="uq_firmware_type_version_hw"),
        Index("idx_firmware_lookup", "device_type_id", "version_string"),
    )

    def __repr__(self) -> str:
        return f"<FirmwareVersion(version='{self.version_string}', hw='{self.hardware_revision}')>"


class OTADeployment(Base, TimestampMixin):
    """
    Over-The-Air deployment job targeting an individual physical device.
    Tracks state machine from trigger to download, reboot, self-test, or rollback.
    """
    __tablename__ = "ota_deployments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    firmware_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("firmware_versions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    deployment_status: Mapped[str] = mapped_column(
        String(32),
        default="PENDING",
        index=True,
        nullable=False,
    )  # PENDING, DOWNLOADING, INSTALLING, REBOOTING, SUCCESS, FAILED, ROLLED_BACK
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    firmware_version: Mapped["FirmwareVersion"] = relationship("FirmwareVersion", back_populates="deployments")
    device: Mapped["Device"] = relationship("Device", back_populates="ota_deployments")
    created_by_user: Mapped[Optional["User"]] = relationship("User")

    __table_args__ = (
        Index("idx_ota_device_status", "device_id", "deployment_status"),
    )

    def __repr__(self) -> str:
        return f"<OTADeployment(device_id='{self.device_id}', status='{self.deployment_status}')>"
