"""
Pydantic schemas for Vending Machine module configuration and transactions.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class QRSettingsResponse(BaseModel):
    """Configuration for dynamic QR payments on a vending machine."""
    device_id: str
    provider: str
    upi_merchant_vpa: str
    qr_timeout_seconds: int
    dynamic_pricing_enabled: bool
    is_active: bool


class QRSettingsUpdateRequest(BaseModel):
    """Payload to update QR payment gateway settings."""
    upi_merchant_vpa: Optional[str] = Field(None, description="UPI merchant virtual payment address (e.g. apex@icici)")
    qr_timeout_seconds: Optional[int] = Field(None, ge=30, le=600, description="Display countdown timer in seconds")
    dynamic_pricing_enabled: Optional[bool] = None


class CoinSettingsResponse(BaseModel):
    """Configuration for electronic coin pulse acceptor."""
    device_id: str
    acceptor_mode: str
    pulse_mappings: Dict[str, int]  # e.g. {"1": 100, "2": 200, "5": 500, "10": 1000} (in paise)
    debounce_ms: int
    coin_escrow_enabled: bool
    change_dispenser_fitted: bool


class CoinSettingsUpdateRequest(BaseModel):
    """Payload to update electronic coin acceptor pulse mappings."""
    pulse_mappings: Optional[Dict[str, int]] = Field(None, description="Pulse count to value mapping in paise")
    debounce_ms: Optional[int] = Field(None, ge=10, le=200, description="Hardware debounce delay in ms")
    change_dispenser_fitted: Optional[bool] = None


class VendingTransactionResponse(BaseModel):
    """Transaction record for vending machine."""
    id: str
    transaction_number: str
    device_id: str
    transaction_type: str
    amount_in_rupees: float
    coins_inserted: Optional[Dict[str, int]] = None
    change_dispensed: int
    dispense_status: str
    transacted_at: datetime

    model_config = {"from_attributes": True}


class ClientFleetCapabilityItem(BaseModel):
    """Summary of a client's machine with dynamic module capability flags."""
    device_id: str
    product_type: str
    status: str
    is_online: bool
    config_version: int
    firmware_version: str
    has_qr_payment: bool
    has_coin_payment: bool
    has_rfid_access: bool
    modules: Dict[str, bool]


# ------------------------------------------------------------------------------
# PRODUCT CATALOG SCHEMAS
# ------------------------------------------------------------------------------

class ProductCreateRequest(BaseModel):
    """Payload to create a new catalog product for a client tenant."""
    product_code: str = Field(..., description="Unique product SKU/code (e.g. BEV-COKE-300)")
    name: str = Field(..., description="Display name of the product")
    price: int = Field(..., ge=1, description="Price in smallest currency unit (paise: 4000 = ₹40.00)")
    description: Optional[str] = Field(None, description="Product description")
    image_url: Optional[str] = Field(None, description="Product image asset URL")
    is_active: bool = Field(True, description="Active status for dispensing")


class ProductUpdateRequest(BaseModel):
    """Payload to update an existing catalog product."""
    name: Optional[str] = None
    price: Optional[int] = Field(None, ge=1, description="Updated price in paise")
    description: Optional[str] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


class ProductResponse(BaseModel):
    """Catalog product detail."""
    id: str
    client_id: str
    product_code: str
    name: str
    description: Optional[str] = None
    price: int
    price_rupees: float
    image_url: Optional[str] = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ------------------------------------------------------------------------------
# MACHINE SLOT MANAGEMENT SCHEMAS
# ------------------------------------------------------------------------------

class MachineSlotResponse(BaseModel):
    """Physical dispensing slot configuration and live stock status."""
    id: str
    device_id: str
    slot_number: int
    slot_code: str
    product_id: Optional[str] = None
    product_code: Optional[str] = None
    product_name: Optional[str] = None
    price: int
    price_rupees: float
    override_price: Optional[int] = None
    motor_pin: Optional[int] = None
    pulse_duration_ms: int
    capacity: int
    current_stock: int
    is_active: bool


class MachineSlotConfigureRequest(BaseModel):
    """Payload to configure or reassign a physical vending machine slot."""
    product_id: Optional[str] = Field(None, description="Catalog product ID to bind to this slot")
    override_price: Optional[int] = Field(None, description="Optional slot-specific price override in paise")
    motor_pin: Optional[int] = Field(None, description="ESP32 GPIO / relay pin index driving the coil motor")
    pulse_duration_ms: Optional[int] = Field(None, ge=100, le=5000, description="Motor run pulse duration in ms")
    capacity: Optional[int] = Field(None, ge=1, le=100, description="Max physical capacity")
    current_stock: Optional[int] = Field(None, ge=0, description="Current stock level")
    is_active: Optional[bool] = Field(None, description="Slot active status")


class MachineSlotBulkItem(BaseModel):
    """Single slot entry within a bulk configuration request."""
    slot_number: int = Field(..., ge=1, le=100)
    product_id: Optional[str] = None
    override_price: Optional[int] = None
    motor_pin: Optional[int] = None
    pulse_duration_ms: Optional[int] = 500
    capacity: Optional[int] = 10
    current_stock: Optional[int] = 0
    is_active: Optional[bool] = True


class MachineSlotBulkConfigureRequest(BaseModel):
    """Payload to configure multiple slots on a vending machine simultaneously."""
    slots: List[MachineSlotBulkItem]


class MachineSlotRestockRequest(BaseModel):
    """Payload to record inventory restocking for a vending machine slot."""
    quantity_added: Optional[int] = Field(None, ge=1, description="Quantity to increment current stock by")
    new_stock_level: Optional[int] = Field(None, ge=0, description="Directly set exact stock level")

