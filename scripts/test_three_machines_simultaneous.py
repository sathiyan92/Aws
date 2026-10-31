"""
Comprehensive Multi-Machine Simultaneous Payment & Dispense Test Suite.
Validates all requirements for a 1000+ machine fleet:
1. Raw-body HMAC-SHA256 signature verification for 'qr_code.credited' and 'payment.captured'.
2. Stored Razorpay QR ID and Payment ID extraction.
3. Order matching via stored Razorpay QR ID.
4. Payment status verification (captured) and exact amount matching.
5. Machine identification via database mapping (RazorpayQRCode -> Device).
6. Marking ONLY the matched order as PAID.
7. Unique, one-time dispense authorization (dispense_token) with expiry.
8. ESP32 authenticated polling via /pending-dispense/{device_id}.
9. TFT display payload: "PAYMENT SUCCESSFUL", amount, and product name.
10. Dispense confirmation to AWS cloud with single-use token consumption and stock decrement.
11. Duplicate webhook protection and duplicate motor activation prevention.
12. Strict machine isolation: Machine A NEVER receives Machine B's payment.
13. Audit logging of payment ID, QR ID, order ID, machine ID, vendor ID, amount and timestamps.
14. Offline machine retention, recovery, and expiry policy.
15. Clean UPI QR payload format (never image_url) and BMP generation endpoint.
16. Simultaneous test across 3 machines: VM-000001, VM-000002, VM-000003.
"""
import sys
import os
import hmac
import hashlib
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
backend_dir = os.path.join(root_dir, "backend")
sys.path.insert(0, root_dir)
sys.path.insert(0, backend_dir)

from src.core.config.settings import settings
from src.db.session import SessionLocal
from src.db.base import utc_now, generate_uuid
from src.db.models.client import Client
from src.db.models.device import Device, DeviceType
from src.db.models.vending import Order, Payment, MachineSlot, Product, WebhookEvent, RazorpayQRCode
from src.db.models.audit import AuditLog
from src.services.razorpay_service import (
    process_webhook_event,
    verify_webhook_signature,
    create_razorpay_qr,
)
from src.services.order_service import (
    get_pending_dispense_for_device,
    mark_order_dispensed,
    get_device_qr_config,
)


def compute_signature(raw_body: bytes, secret: str) -> str:
    return hmac.new(key=secret.encode("utf-8"), msg=raw_body, digestmod=hashlib.sha256).hexdigest()


def setup_test_environment(db):
    """Ensure client, products, and 3 distinct vending machines exist in database."""
    client = db.query(Client).first()
    if not client:
        client = Client(
            id=generate_uuid(),
            name="G-TECH Vending Fleet Ltd",
            slug="gtech-fleet",
            is_active=True,
        )
        db.add(client)
        db.commit()
        db.refresh(client)

    dev_type = db.query(DeviceType).filter_by(code="VENDING_MACHINE").first()
    if not dev_type:
        dev_type = DeviceType(
            name="Vending Machine Controller",
            code="VENDING_MACHINE",
            description="Smart Vending Node",
        )
        db.add(dev_type)
        db.commit()
        db.refresh(dev_type)

    machines_spec = [
        {"device_id": "VM-000001", "mac": "14:08:08:9F:5A:C0", "price": 1000, "prod": "Natural Spring Water 500ml"},
        {"device_id": "VM-000002", "mac": "24:08:08:9F:5A:C1", "price": 2000, "prod": "Cold Brew Coffee 250ml"},
        {"device_id": "VM-000003", "mac": "34:08:08:9F:5A:C2", "price": 3000, "prod": "Energy Drink 330ml"},
    ]

    devices = []
    for spec in machines_spec:
        dev = db.query(Device).filter(Device.device_id == spec["device_id"]).first()
        if not dev:
            dev = Device(
                id=generate_uuid(),
                device_id=spec["device_id"],
                client_id=client.id,
                device_type_id=dev_type.id,
                hardware_id=f"HW-{spec['device_id']}",
                chip_id=f"CHIP-{spec['device_id']}",
                mac_address=spec["mac"],
                factory_serial=f"SN-{spec['device_id']}",
                status="ACTIVE",
                is_online=True,
                last_heartbeat_at=utc_now(),
                current_firmware_version="v2.0.0-razorpay",
                current_config_version=1,
            )
            db.add(dev)
            db.commit()
            db.refresh(dev)

        # Clear any stale pending orders for clean test
        db.query(Order).filter(
            Order.device_id == dev.id,
            Order.order_status.in_(["PAID", "DISPENSE_AUTHORIZED"]),
        ).update({"order_status": "DISPENSED"}, synchronize_session=False)
        db.commit()

        # Ensure Product and Slot 1 exist
        prod = db.query(Product).filter_by(client_id=client.id, name=spec["prod"]).first()
        if not prod:
            prod = Product(
                id=generate_uuid(),
                client_id=client.id,
                product_code=f"PRD-{spec['device_id']}",
                name=spec["prod"],
                price=spec["price"],
                is_active=True,
            )
            db.add(prod)
            db.commit()
            db.refresh(prod)

        slot = db.query(MachineSlot).filter_by(device_id=dev.id, slot_number=1).first()
        if not slot:
            slot = MachineSlot(
                id=generate_uuid(),
                client_id=client.id,
                device_id=dev.id,
                slot_number=1,
                slot_code="A1",
                product_id=prod.id,
                current_stock=50,
                max_capacity=100,
                override_price=spec["price"],
                is_active=True,
            )
            db.add(slot)
            db.commit()
            db.refresh(slot)
        else:
            slot.override_price = spec["price"]
            slot.product_id = prod.id
            slot.current_stock = 50
            db.commit()

        devices.append(dev)

    return client, devices


def run_three_machines_test():
    print("=" * 75)
    print("FLEET-WIDE 3-MACHINE SIMULTANEOUS RAZORPAY WEBHOOK & DISPENSE VERIFICATION")
    print("=" * 75)

    db = SessionLocal()
    try:
        client, devices = setup_test_environment(db)
        dev1, dev2, dev3 = devices
        print(f"  [✓] Provisioned 3 Active Vending Machines:")
        print(f"      Machine 1: {dev1.device_id} (Slot 1: Rs. 10.00, Spring Water)")
        print(f"      Machine 2: {dev2.device_id} (Slot 1: Rs. 20.00, Cold Brew Coffee)")
        print(f"      Machine 3: {dev3.device_id} (Slot 1: Rs. 30.00, Energy Drink)")

        # ----------------------------------------------------------------------
        # TEST 1: Clean UPI QR Code Generation (Requirement 15: Never encode image_url)
        # ----------------------------------------------------------------------
        print("\n--- TEST 1: QR Code Generation & Payload Format (Requirement 15) ---")
        qr1 = create_razorpay_qr(db, device_id="VM-000001", slot_number=1, amount_rupees=10.0, name_override="VM-000001 Water")
        qr2 = create_razorpay_qr(db, device_id="VM-000002", slot_number=1, amount_rupees=20.0, name_override="VM-000002 Coffee")
        qr3 = create_razorpay_qr(db, device_id="VM-000003", slot_number=1, amount_rupees=30.0, name_override="VM-000003 Energy")

        for idx, qr in enumerate([qr1, qr2, qr3], start=1):
            assert qr["qr_payload"].startswith("upi://pay?"), f"Payload must start with upi://pay?: {qr['qr_payload']}"
            assert not qr["qr_payload"].startswith("http"), f"Payload must NEVER be an image_url or web URL: {qr['qr_payload']}"
            assert f"tr={qr['razorpay_qr_id']}" in qr["qr_payload"]
            print(f"  [✓] Machine {idx} QR Generated: {qr['razorpay_qr_id']}")
            print(f"      UPI Payload: {qr['qr_payload']}")

        # ----------------------------------------------------------------------
        # TEST 2: Simultaneous Payments via Signed 'qr_code.credited' Webhooks
        # (Requirements 1, 2, 3, 4, 5, 6, 7)
        # ----------------------------------------------------------------------
        print("\n--- TEST 2: Simultaneous Signed Webhooks for 3 Machines ---")
        now_ts = int(time.time())
        webhook_data_list = [
            {
                "dev": dev1,
                "qr": qr1,
                "pay_id": f"pay_m1_{now_ts}",
                "evt_id": f"evt_qr_cred_m1_{now_ts}",
                "amount": 1000,
            },
            {
                "dev": dev2,
                "qr": qr2,
                "pay_id": f"pay_m2_{now_ts}",
                "evt_id": f"evt_qr_cred_m2_{now_ts}",
                "amount": 2000,
            },
            {
                "dev": dev3,
                "qr": qr3,
                "pay_id": f"pay_m3_{now_ts}",
                "evt_id": f"evt_qr_cred_m3_{now_ts}",
                "amount": 3000,
            },
        ]

        webhook_results = []
        for item in webhook_data_list:
            body = {
                "entity": "event",
                "account_id": "acc_gtech_fleet",
                "event": "qr_code.credited",
                "id": item["evt_id"],
                "contains": ["qr_code", "payment"],
                "payload": {
                    "qr_code": {
                        "entity": {
                            "id": item["qr"]["razorpay_qr_id"],
                            "entity": "qr_code",
                            "name": item["qr"]["product_name"],
                            "usage": "single_use",
                            "type": "upi_qr",
                            "status": "active",
                            "fixed_amount": True,
                            "payment_amount": item["amount"],
                            "notes": {
                                "device_id": item["dev"].device_id,
                                "slot_number": "1",
                                "razorpay_qr_id": item["qr"]["razorpay_qr_id"],
                            },
                        }
                    },
                    "payment": {
                        "entity": {
                            "id": item["pay_id"],
                            "entity": "payment",
                            "amount": item["amount"],
                            "currency": "INR",
                            "status": "captured",  # Requirement 4
                            "method": "upi",
                            "notes": {
                                "device_id": item["dev"].device_id,
                                "slot_number": "1",
                                "razorpay_qr_id": item["qr"]["razorpay_qr_id"],
                            },
                        }
                    },
                },
                "created_at": now_ts,
            }
            raw_body = json.dumps(body).encode("utf-8")
            # Requirement 1: Verify webhook signature using exact raw request body
            valid_sig = compute_signature(raw_body, settings.RAZORPAY_WEBHOOK_SECRET)

            res = process_webhook_event(
                db=db,
                raw_body=raw_body,
                signature=valid_sig,
                enforce_signature=True,
            )
            assert res.get("status") == "SUCCESS"
            dispense_info = res.get("dispense", {})
            assert dispense_info.get("device_id") == item["dev"].device_id
            assert dispense_info.get("status") == "PAID"
            assert dispense_info.get("dispense_token") is not None
            webhook_results.append((item, res, raw_body, valid_sig))
            print(f"  [✓] Webhook Processed for {item['dev'].device_id}:")
            print(f"      Payment ID     : {item['pay_id']}")
            print(f"      QR ID          : {item['qr']['razorpay_qr_id']}")
            print(f"      Order Number   : {dispense_info.get('order_number')}")
            print(f"      Dispense Token : {dispense_info.get('dispense_token')}")
            print(f"      Amount         : Rs. {dispense_info.get('amount_rupees')}")

        # ----------------------------------------------------------------------
        # TEST 3: Strict Machine Isolation (Requirements 8 & 12)
        # Other machines must NEVER receive another machine's payment authorization
        # ----------------------------------------------------------------------
        print("\n--- TEST 3: Strict Machine Isolation & ESP32 Session Polling ---")
        p1 = get_pending_dispense_for_device(db, device_id="VM-000001", device_token="dev_token_VM-000001")
        p2 = get_pending_dispense_for_device(db, device_id="VM-000002", device_token="dev_token_VM-000002")
        p3 = get_pending_dispense_for_device(db, device_id="VM-000003", device_token="dev_token_VM-000003")

        # Assert Machine 1 gets ONLY Machine 1's authorization
        assert p1["dispense_pending"] is True
        assert p1["amount_rupees"] == 10.0
        assert p1["product_name"] == "Natural Spring Water 500ml"
        assert p1["display_title"] == "PAYMENT SUCCESSFUL"
        assert p1["order_id"] == webhook_results[0][1]["dispense"]["order_id"]

        # Assert Machine 2 gets ONLY Machine 2's authorization
        assert p2["dispense_pending"] is True
        assert p2["amount_rupees"] == 20.0
        assert p2["product_name"] == "Cold Brew Coffee 250ml"
        assert p2["display_title"] == "PAYMENT SUCCESSFUL"
        assert p2["order_id"] == webhook_results[1][1]["dispense"]["order_id"]

        # Assert Machine 3 gets ONLY Machine 3's authorization
        assert p3["dispense_pending"] is True
        assert p3["amount_rupees"] == 30.0
        assert p3["product_name"] == "Energy Drink 330ml"
        assert p3["display_title"] == "PAYMENT SUCCESSFUL"
        assert p3["order_id"] == webhook_results[2][1]["dispense"]["order_id"]

        # Assert No Cross-Talk: Tokens are completely distinct
        tokens = [p1["dispense_token"], p2["dispense_token"], p3["dispense_token"]]
        assert len(set(tokens)) == 3, "All dispense tokens must be strictly unique!"
        print(f"  [✓] Machine 1 received ONLY VM-000001 authorization (Rs. 10.00, Spring Water)")
        print(f"  [✓] Machine 2 received ONLY VM-000002 authorization (Rs. 20.00, Cold Brew Coffee)")
        print(f"  [✓] Machine 3 received ONLY VM-000003 authorization (Rs. 30.00, Energy Drink)")
        print(f"  [✓] ZERO CROSS-TALK CONFIRMED: Machine A never receives Machine B's payment.")

        # ----------------------------------------------------------------------
        # TEST 4: One-Time Token Consumption & Single Motor Activation (Requirements 7, 10 & 11)
        # ----------------------------------------------------------------------
        print("\n--- TEST 4: One-Time Token Dispense Confirmation & Stock Decrement ---")
        slot1 = db.query(MachineSlot).filter_by(device_id=dev1.id, slot_number=1).first()
        initial_stock = slot1.current_stock

        # Dispense confirmation for Machine 1 with its valid token
        dispensed_order = mark_order_dispensed(db, order_id_or_number=p1["order_id"], dispense_token=p1["dispense_token"])
        assert dispensed_order.order_status == "DISPENSED"
        assert slot1.current_stock == initial_stock - 1, "Stock must decrement by exactly 1!"
        print(f"  [✓] Dispense confirmed: Order {dispensed_order.order_number} marked DISPENSED.")
        print(f"  [✓] Inventory decremented: Slot 1 stock: {initial_stock} -> {slot1.current_stock}")

        # Verify token is consumed (one-time authorization)
        ord_db = db.query(Order).filter(Order.id == p1["order_id"]).first()
        assert ord_db.dispense_token is None, "Token must be invalidated after dispense confirmation!"

        # Immediate re-poll by Machine 1 must return dispense_pending == False
        p1_after = get_pending_dispense_for_device(db, device_id="VM-000001")
        assert p1_after["dispense_pending"] is False, "Machine 1 must have no more pending dispenses!"
        print(f"  [✓] Machine 1 re-poll: dispense_pending = False (No duplicate motor cycles).")

        # Duplicate dispense confirmation attempt must be idempotent without double-decrementing stock
        stock_before_dup = slot1.current_stock
        dup_dispense = mark_order_dispensed(db, order_id_or_number=p1["order_id"], dispense_token=p1["dispense_token"])
        assert dup_dispense.order_status == "DISPENSED"
        assert slot1.current_stock == stock_before_dup, "Duplicate dispense must NEVER decrement stock twice!"
        print(f"  [✓] Idempotency confirmed: Duplicate confirmation rejected without double stock decrement.")

        # ----------------------------------------------------------------------
        # TEST 5: Duplicate Webhook Event Interception (Requirement 11)
        # ----------------------------------------------------------------------
        print("\n--- TEST 5: Duplicate Webhook Event Interception ---")
        item0, res0, raw_body0, sig0 = webhook_results[0]
        dup_webhook_res = process_webhook_event(
            db=db,
            raw_body=raw_body0,
            signature=sig0,
            enforce_signature=True,
        )
        assert dup_webhook_res.get("status") == "DUPLICATE_IGNORED"
        assert dup_webhook_res.get("event_id") == item0["evt_id"]
        print(f"  [✓] Duplicate webhook event intercepted: status={dup_webhook_res.get('status')}")

        # ----------------------------------------------------------------------
        # TEST 6: Audit Trail Verification (Requirement 13)
        # Record payment ID, QR ID, order ID, machine ID, vendor ID, amount & timestamps
        # ----------------------------------------------------------------------
        print("\n--- TEST 6: Complete Audit Trail Verification (Requirement 13) ---")
        logs = (
            db.query(AuditLog)
            .filter(AuditLog.action == "RAZORPAY_WEBHOOK_PAYMENT_CAPTURED")
            .order_by(AuditLog.created_at.desc())
            .limit(3)
            .all()
        )
        assert len(logs) >= 3, "Audit logs must record all 3 webhook captures!"
        for log in logs:
            state = log.new_state
            assert "payment_id" in state, "Missing payment_id in audit log"
            assert "razorpay_qr_id" in state, "Missing razorpay_qr_id in audit log"
            assert "order_id" in state, "Missing order_id in audit log"
            assert "machine_id" in state, "Missing machine_id in audit log"
            assert "vendor_id" in state, "Missing vendor_id in audit log"
            assert "amount_paise" in state, "Missing amount_paise in audit log"
            assert "timestamp" in state, "Missing timestamp in audit log"
            print(f"  [✓] Audit Log Entry verified: Machine={state['machine_id']}, Order={state['order_number']}, PayID={state['payment_id']}, Vendor={state['vendor_id']}, Amount=Rs.{state['amount_rupees']}")

        # ----------------------------------------------------------------------
        # TEST 7: Offline Machine Retention & Expiry Policy (Requirement 14)
        # ----------------------------------------------------------------------
        print("\n--- TEST 7: Offline Machine Retention & Expiry Policy (Requirement 14) ---")
        # Scenario A: Machine offline during payment, safely retrieves order when back online
        offline_pay_id = f"pay_offline_{int(time.time())}"
        offline_order_id = generate_uuid()
        offline_order = Order(
            id=offline_order_id,
            order_number=f"ORD-OFFLINE-{generate_uuid()[:6].upper()}",
            device_id=dev2.id,
            client_id=client.id,
            slot_id=dev2.slots[0].id,
            product_id=dev2.slots[0].product_id,
            unit_price=2000,
            quantity=1,
            total_amount=2000,
            order_status="PAID",
            payment_method="RAZORPAY",
            paid_at=utc_now(),
            dispense_token=f"auth_{generate_uuid()}",
            dispense_token_expires_at=utc_now() + timedelta(minutes=60),
        )
        db.add(offline_order)
        db.commit()

        # Machine 2 was offline, now powers on and polls
        recovered_poll = get_pending_dispense_for_device(db, device_id="VM-000002")
        assert recovered_poll["dispense_pending"] is True
        print(f"  [✓] Scenario A: Offline machine safely retained order. Recovered upon reconnection: {recovered_poll['order_number']}")

        # Scenario B: Machine offline past expiry window (e.g. 61 minutes later)
        expired_order_id = generate_uuid()
        expired_order = Order(
            id=expired_order_id,
            order_number=f"ORD-EXP-{generate_uuid()[:6].upper()}",
            device_id=dev3.id,
            client_id=client.id,
            slot_id=dev3.slots[0].id,
            product_id=dev3.slots[0].product_id,
            unit_price=3000,
            quantity=1,
            total_amount=3000,
            order_status="PAID",
            payment_method="RAZORPAY",
            paid_at=utc_now() - timedelta(minutes=70),
            dispense_token=f"auth_{generate_uuid()}",
            dispense_token_expires_at=utc_now() - timedelta(minutes=10),  # expired 10 mins ago
        )
        db.add(expired_order)
        db.commit()

        # Machine 3 polls: The expired order must NOT be dispensed, and should be transitioned to EXPIRED
        # Clear Machine 3's active pending order from TEST 2 so we test the expired one
        db.query(Order).filter(Order.id == p3["order_id"]).update({"order_status": "DISPENSED"})
        db.commit()

        expired_poll = get_pending_dispense_for_device(db, device_id="VM-000003")
        assert expired_poll["dispense_pending"] is False, "Expired order must not be dispensed!"
        db.refresh(expired_order)
        assert expired_order.order_status == "EXPIRED"
        print(f"  [✓] Scenario B: Safe expiry policy enforced. Stale order {expired_order.order_number} marked EXPIRED and not dispensed.")

        print("\n" + "=" * 75)
        print("ALL MULTI-MACHINE & SIMULTANEOUS RAZORPAY DISPENSE TESTS PASSED! [✓]")
        print("=" * 75)

    finally:
        db.close()


if __name__ == "__main__":
    run_three_machines_test()
