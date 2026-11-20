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


# =========================================================================
# MODEL 1: RAZORPAY ROUTE / VENDOR SPLIT PAYOUT SCHEMAS
# =========================================================================

class VendorRouteLinkRequest(BaseModel):
    client_id: str = Field(..., description="Unique ID or client code of the vendor tenant")
    bank_account_number: str = Field(..., min_length=6, description="Vendor bank account number")
    bank_ifsc: str = Field(..., min_length=4, max_length=16, description="IFSC code of vendor bank branch")
    bank_beneficiary_name: str = Field(..., min_length=2, description="Name as registered with the bank")
    commission_percentage: Optional[float] = Field(10.0, ge=0.0, le=100.0, description="Platform commission % (e.g. 10.0% to G-TECH, 90.0% to Vendor)")
    vendor_upi_id: Optional[str] = Field(None, description="Optional vendor UPI VPA for direct settlements")
    razorpay_account_id: Optional[str] = Field(None, description="Optional existing Razorpay Route Linked Account ID (e.g. acc_...)")


class VendorSelfBankUpdateRequest(BaseModel):
    bank_account_number: str = Field(..., min_length=6, description="Vendor bank account number")
    bank_ifsc: str = Field(..., min_length=4, max_length=16, description="IFSC code of vendor bank branch")
    bank_beneficiary_name: str = Field(..., min_length=2, description="Name as registered with the bank")
    vendor_upi_id: Optional[str] = Field(None, description="Optional vendor UPI VPA")
    razorpay_account_id: Optional[str] = Field(None, description="Optional existing Razorpay Route Linked Account ID (e.g. acc_...)")
