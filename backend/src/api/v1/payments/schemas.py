"""
Pydantic Schemas for Razorpay Payment Gateway & QR Subsystem.
"""
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class RazorpayQRCreateRequest(BaseModel):
    device_id: str = Field(..., description="Target machine identifier e.g. VM-000001")
    slot_number: Optional[int] = Field(1, description="Physical vending slot number (default: 1)")
    amount_rupees: Optional[float] = Field(None, description="Optional custom price in Rupees (defaults to slot price)")
    usage: Optional[str] = Field("single_use", description="QR usage type: 'single_use' or 'multiple_use'")
    name: Optional[str] = Field(None, description="Optional custom label for QR code")


class RazorpayQRResponse(BaseModel):
    id: str
    razorpay_qr_id: str
    device_id: str
    slot_number: int
    product_name: str
    amount_rupees: float
    amount_paise: int
    usage: str
    qr_payload: str
    image_url: Optional[str] = None
    status: str


class RazorpayConfigResponse(BaseModel):
    key_id: str
    test_mode: bool
    currency: str


class RazorpayVerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class RazorpayVerifyPaymentResponse(BaseModel):
    valid: bool
    message: str
