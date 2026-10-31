"""
Central export for all SQLAlchemy models in the Multi-Tenant IoT Fleet Platform.
Ensures all declarative mappings are loaded by Alembic and runtime metadata.
"""
from src.db.base import Base, generate_uuid, utc_now
from src.db.models.client import Client
from src.db.models.user import User
from src.db.models.device import DeviceType, Device, DeviceModule, DeviceCredential
from src.db.models.config import DeviceConfig, ConfigurationVersion
from src.db.models.vending import Product, MachineSlot, Order, Payment, Transaction, WebhookEvent, RazorpayQRCode
from src.db.models.rfid import Employee, RFIDCard, AttendanceEvent
from src.db.models.firmware import FirmwareVersion, OTADeployment
from src.db.models.telemetry import DeviceHeartbeat, DeviceLog
from src.db.models.audit import AuditLog

__all__ = [
    "Base",
    "generate_uuid",
    "utc_now",
    "Client",
    "User",
    "DeviceType",
    "Device",
    "DeviceModule",
    "DeviceCredential",
    "DeviceConfig",
    "ConfigurationVersion",
    "Product",
    "MachineSlot",
    "Order",
    "Payment",
    "Transaction",
    "WebhookEvent",
    "RazorpayQRCode",
    "Employee",
    "RFIDCard",
    "AttendanceEvent",
    "FirmwareVersion",
    "OTADeployment",
    "DeviceHeartbeat",
    "DeviceLog",
    "AuditLog",
]
