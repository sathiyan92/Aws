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
