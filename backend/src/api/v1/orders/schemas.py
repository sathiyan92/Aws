"""
Pydantic Schemas for Dynamic QR Orders & Payment Intent Lifecycle.
"""
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field


class OrderInitiateRequest(BaseModel):
    """Payload to initiate a dynamic QR purchase intent for a specific vending slot."""
    device_id: str = Field(..., description="Vending Machine Device ID (e.g. VM-000001)")
    slot_number: int = Field(..., ge=1, le=100, description="Physical dispensing slot number")
    customer_phone: Optional[str] = Field(None, description="Optional customer phone number for SMS receipt")
    customer_vpa: Optional[str] = Field(None, description="Optional customer UPI VPA")


class OrderInitiateResponse(BaseModel):
    """Response containing dynamic UPI payload, QR matrix preview, and expiration timer."""
    order_id: str = Field(..., description="Unique Order UUID")
    order_number: str = Field(..., description="Human-readable order tracking number")
    device_id: str
    slot_number: int
    slot_code: str
    product_id: str
    product_name: str
    product_code: str
    amount_paise: int = Field(..., description="Resolved price in smallest currency unit")
    amount_rupees: float = Field(..., description="Price in rupees (₹)")
    currency: str = "INR"
    qr_payload: str = Field(..., description="Dynamic UPI URI with merchant VPA and order ref")
    qr_image_data: Optional[str] = Field(None, description="Data URI or SVG for dashboard display")
    qr_ascii_preview: Optional[str] = Field(None, description="Terminal/LCD ASCII frame preview")
    order_status: str = "PENDING"
    payment_status: str = "INITIATED"
    timeout_seconds: int = 180
    expires_at: datetime
    created_at: datetime


class OrderDetailResponse(BaseModel):
    """Detailed purchase order status and dynamic payment intent resolution."""
    order_id: str
    order_number: str
    device_id: str
    slot_number: int
    product_name: str
    product_code: str
    amount_paise: int
    amount_rupees: float
    currency: str = "INR"
    order_status: str
    payment_method: str
    payment_status: Optional[str] = None
    gateway_provider: Optional[str] = None
    qr_payload: Optional[str] = None
    expires_at: Optional[datetime] = None
    seconds_remaining: Optional[int] = None
    dispensed_at: Optional[datetime] = None
    created_at: datetime


class OrderCancelResponse(BaseModel):
    """Response when a pending order is cancelled by user or invalidated by coin insertion."""
    order_id: str
    order_number: str
    order_status: str = "CANCELLED"
    cancelled_at: datetime
    message: str = "Order cancelled successfully"


class OrderListResponse(BaseModel):
    """List of orders for a machine or tenant."""
    orders: List[OrderDetailResponse]
    total_count: int


class QRConfigResponse(BaseModel):
    """Active QR configuration returned to ESP32 node and Vendor dashboard."""
    device_id: str
    razorpay_upi_vpa: str
    qr_payload: str
    amount_rupees: float
    product_name: str
    config_version: int


class QRConfigUpdate(BaseModel):
    """Payload sent by Vendor or Manufacturer to change QR, UPI VPA, or Price dynamically."""
    razorpay_upi_vpa: Optional[str] = Field(None, description="New Razorpay UPI VPA (e.g. vendor123@icici)")
    custom_qr_payload: Optional[str] = Field(None, description="Custom static or dynamic QR string")
    amount_rupees: Optional[float] = Field(None, ge=1.0, description="Updated item price in Rupees")
    product_name: Optional[str] = Field(None, description="Updated product name")

