"""
Unit & Integration Tests for Model 1: Razorpay Route Automated Vendor Split Payouts.
"""
import pytest
from sqlalchemy.orm import Session

from src.db.session import SessionLocal
from src.db.base import generate_uuid, utc_now
from src.db.models.client import Client
from src.db.models.device import Device
from src.db.models.vending import Order, MachineSlot, Product, PayoutTransfer
from src.services.razorpay_service import (
    create_or_update_route_linked_account,
    execute_route_split_transfer,
)
from src.api.v1.payments.routes import (
    link_vendor_route_account,
    list_route_vendors,
    get_route_settlements_summary,
    list_route_payout_transfers,
    get_vendor_route_details,
    vendor_self_update_bank_details,
)
from src.api.v1.payments.schemas import (
    VendorRouteLinkRequest,
    VendorSelfBankUpdateRequest,
)


def test_create_or_update_route_linked_account():
    db = SessionLocal()
    try:
        vendor_client = Client(
            id=generate_uuid(),
            name="Test Route Vendor Ltd",
            client_code=f"TRV_{generate_uuid()[:6].upper()}",
            contact_email=f"vendor_{generate_uuid()[:6]}@testroute.com",
            status="ACTIVE",
        )
        db.add(vendor_client)
        db.commit()

        res = create_or_update_route_linked_account(
            db=db,
            client=vendor_client,
            bank_account_number="98765432101234",
            bank_ifsc="HDFC0001234",
            bank_beneficiary_name="Test Route Vendor Ltd",
            commission_percentage=12.5,
            vendor_upi_id="testvendor@okhdfcbank",
        )

        assert res["client_id"] == vendor_client.id
        assert res["commission_percentage"] == 12.5
        assert vendor_client.payout_status == "ACTIVE"
        assert vendor_client.razorpay_account_id is not None
        assert vendor_client.bank_ifsc == "HDFC0001234"
        assert vendor_client.razorpay_merchant_vpa == "testvendor@okhdfcbank"
    finally:
        db.close()


def test_execute_route_split_transfer():
    db = SessionLocal()
    try:
        d = db.query(Device).first()
        assert d is not None, "At least one device should be seeded"
        c = d.client or db.query(Client).first()
        c.commission_percentage = 10.0
        c.razorpay_account_id = f"acc_sim_{generate_uuid()[:8]}"
        c.payout_status = "ACTIVE"
        db.commit()

        s = db.query(MachineSlot).filter_by(device_id=d.id).first()
        p = db.query(Product).first()

        order = Order(
            id=generate_uuid(),
            order_number=f"ORD-SPLIT-{generate_uuid()[:6]}",
            client_id=c.id,
            device_id=d.id,
            slot_id=s.id if s else None,
            product_id=p.id if p else None,
            payment_method="QR_PAYMENT",
            unit_price=2000,
            quantity=1,
            total_amount=2000,
            order_status="PAID",
        )
        db.add(order)
        db.commit()

        # Execute split transfer
        transfer = execute_route_split_transfer(
            db=db,
            payment_id="pay_sim_123456789",
            order=order,
            device=d,
            total_amount_paise=2000,
        )

        assert transfer is not None
        assert transfer.total_amount_paise == 2000
        assert transfer.platform_fee_paise == 200  # 10% of 2000
        assert transfer.vendor_amount_paise == 1800  # 90% of 2000
        assert transfer.commission_percentage == 10.0
        assert transfer.status in ("SETTLED", "PENDING")
        assert transfer.razorpay_transfer_id is not None

        # Verify idempotency
        transfer_dup = execute_route_split_transfer(
            db=db,
            payment_id="pay_sim_123456789",
            order=order,
            device=d,
            total_amount_paise=2000,
        )
        assert transfer_dup.id == transfer.id
    finally:
        db.close()


def test_route_api_endpoints():
    db = SessionLocal()
    try:
        c = Client(
            id=generate_uuid(),
            name="API Linked Merchant",
            client_code=f"ALM_{generate_uuid()[:6].upper()}",
            contact_email=f"merchant_{generate_uuid()[:6]}@store.com",
            status="ACTIVE",
        )
        db.add(c)
        db.commit()
        client_id = c.id

        # 1. Test Link Vendor API
        link_payload = VendorRouteLinkRequest(
            client_id=client_id,
            bank_account_number="50100234567890",
            bank_ifsc="SBIN0001234",
            bank_beneficiary_name="API Linked Merchant Store",
            commission_percentage=15.0,
            vendor_upi_id="merchant@oksbi",
        )
        res_link = link_vendor_route_account(payload=link_payload, db=db)
        assert res_link["client_id"] == client_id
        assert res_link["commission_percentage"] == 15.0
        assert res_link["payout_status"] == "ACTIVE"

        # 2. Test Route Summary API
        summary = get_route_settlements_summary(db=db)
        assert "total_volume_rupees" in summary
        assert "total_vendor_payouts_rupees" in summary
        assert "total_platform_commission_rupees" in summary
        assert "linked_vendors_count" in summary

        # 3. Test Route Vendors API
        vendors = list_route_vendors(db=db)
        assert isinstance(vendors, list)
        target = next((v for v in vendors if v["client_id"] == client_id), None)
        assert target is not None
        assert target["commission_percentage"] == 15.0
        assert target["vendor_percentage"] == 85.0

        # 4. Test Route Payouts List API
        payouts = list_route_payout_transfers(limit=10, client_id=None, db=db)
        assert isinstance(payouts, list)

        # 5. Test Vendor Details API
        detail = get_vendor_route_details(client_id=client_id, db=db)
        assert detail["client_id"] == client_id
        assert detail["commission_percentage"] == 15.0

        # 6. Test Vendor Self Update API
        self_update_payload = VendorSelfBankUpdateRequest(
            bank_account_number="50100999999999",
            bank_ifsc="ICIC0000001",
            bank_beneficiary_name="Updated Merchant Name",
            vendor_upi_id="updated@icici",
        )
        res_self = vendor_self_update_bank_details(client_id=client_id, payload=self_update_payload, db=db)
        assert res_self["bank_ifsc"] == "ICIC0000001"
    finally:
        db.close()
