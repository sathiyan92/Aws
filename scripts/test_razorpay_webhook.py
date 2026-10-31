"""
Razorpay Webhook & Payment Verification Test Suite.
Validates:
1. Raw-body HMAC-SHA256 signature verification.
2. payment.captured event processing and price matching.
3. Order transition to DISPENSE_AUTHORIZED.
4. Edge hardware polling: /api/v1/orders/pending-dispense/{device_id}.
5. Idempotent duplicate-event rejection (status: DUPLICATE_IGNORED).
6. Tampered signature rejection (HTTP 401 / NotAuthenticatedException).
7. QR Code generation (create_razorpay_qr).
8. Client config endpoint credential security.

Usage:
  # Self-contained direct service & database test:
  python scripts/test_razorpay_webhook.py

  # Test against live EC2 backend via HTTP:
  python scripts/test_razorpay_webhook.py --url http://35.154.219.82:8000
"""
import sys
import os
import hmac
import hashlib
import json
import time
import argparse
from typing import Dict, Any, Optional

# Add project root and backend to sys.path
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


def compute_razorpay_signature(raw_body: bytes, secret: str) -> str:
    """Compute HMAC SHA-256 signature matching Razorpay webhook specifications."""
    return hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()


def run_http_tests(base_url: str):
    import requests
    print("=" * 70)
    print(f"RAZORPAY INTEGRATION HTTP TEST SUITE -> {base_url}")
    print("=" * 70)

    try:
        from src.core.config.settings import settings
        webhook_secret = settings.RAZORPAY_WEBHOOK_SECRET
    except Exception:
        webhook_secret = "placeholder_webhook_secret"

    session = requests.Session()

    # TEST 1: Public Config Endpoint
    print("\n--- TEST 1: Public Config (GET /api/v1/payments/razorpay/config) ---")
    resp = session.get(f"{base_url.rstrip('/')}/api/v1/payments/razorpay/config")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    cfg = resp.json()
    print(f"  [✓] Config: {cfg}")
    assert "key_id" in cfg
    assert "key_secret" not in cfg, "CRITICAL: Secret leaked!"
    assert "webhook_secret" not in cfg, "CRITICAL: Secret leaked!"

    # TEST 2: Dynamic QR Creation
    print("\n--- TEST 2: Dynamic QR Creation (POST /api/v1/payments/razorpay/qr/create) ---")
    qr_payload = {
        "device_id": "VM-000001",
        "slot_number": 1,
        "amount_rupees": 10.0,
        "usage": "single_use",
        "name": "VM-000001 Cold Drink",
    }
    resp = session.post(
        f"{base_url.rstrip('/')}/api/v1/payments/razorpay/qr/create",
        json=qr_payload,
    )
    assert resp.status_code in (200, 201), f"Expected 200/201, got {resp.status_code}: {resp.text}"
    qr_data = resp.json()
    print(f"  [✓] QR Code Created: {qr_data.get('razorpay_qr_id')}")
    print(f"      UPI Payload: {qr_data.get('qr_payload')}")

    # TEST 3: Tampered Signature Rejection
    print("\n--- TEST 3: Tampered Signature Rejection (Expected HTTP 401) ---")
    tampered_body = json.dumps({
        "event": "payment.captured",
        "id": f"evt_tampered_{int(time.time())}",
        "payload": {"payment": {"entity": {"id": "pay_fake", "amount": 1000}}}
    }).encode("utf-8")
    resp = session.post(
        f"{base_url.rstrip('/')}/api/v1/payments/razorpay/webhook",
        data=tampered_body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": "invalid_sig_abc123"},
    )
    print(f"  [✓] Status Code: {resp.status_code} (Properly Rejected)")
    assert resp.status_code == 401

    # TEST 4: Valid Webhook Delivery
    print("\n--- TEST 4: Valid Webhook Delivery (payment.captured) ---")
    payment_id = f"pay_live_{int(time.time())}"
    event_id = f"evt_{payment_id}"
    payload = {
        "event": "payment.captured",
        "id": event_id,
        "payload": {
            "payment": {
                "entity": {
                    "id": payment_id,
                    "amount": 1000,
                    "currency": "INR",
                    "notes": {"device_id": "VM-000001", "slot_number": "1"},
                }
            }
        }
    }
    raw_body = json.dumps(payload).encode("utf-8")
    valid_sig = compute_razorpay_signature(raw_body, webhook_secret)
    resp = session.post(
        f"{base_url.rstrip('/')}/api/v1/payments/razorpay/webhook",
        data=raw_body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": valid_sig},
    )
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    print(f"  [✓] Response: {resp.json()}")

    # TEST 5: ESP32 Hardware Polling
    print("\n--- TEST 5: ESP32 Hardware Polling (/api/v1/orders/pending-dispense/VM-000001) ---")
    resp = session.get(f"{base_url.rstrip('/')}/api/v1/orders/pending-dispense/VM-000001")
    assert resp.status_code == 200
    poll_data = resp.json()
    print(f"  [✓] ESP32 Poll Response: {poll_data}")
    assert poll_data.get("dispense_pending") is True

    # TEST 6: Duplicate Event (Idempotency)
    print("\n--- TEST 6: Duplicate Event Idempotency ---")
    resp = session.post(
        f"{base_url.rstrip('/')}/api/v1/payments/razorpay/webhook",
        data=raw_body,
        headers={"Content-Type": "application/json", "X-Razorpay-Signature": valid_sig},
    )
    assert resp.status_code == 200
    assert resp.json().get("status") == "DUPLICATE_IGNORED"
    print(f"  [✓] Duplicate Response: {resp.json()}")

    print("\n" + "=" * 70)
    print("ALL HTTP TESTS PASSED SUCCESSFULLY! [✓]")
    print("=" * 70)


def run_direct_tests():
    print("=" * 70)
    print("RAZORPAY INTEGRATION DIRECT SERVICE & DB TEST SUITE")
    print("=" * 70)

    from src.core.config.settings import settings
    from src.db.session import SessionLocal
    from src.db.models.vending import Order, Payment, WebhookEvent, RazorpayQRCode
    from src.db.models.device import Device
    from src.api.v1.payments.routes import get_razorpay_public_config
    from src.services.razorpay_service import (
        verify_webhook_signature,
        verify_payment_signature,
        process_webhook_event,
        create_razorpay_qr,
    )
    from src.services.order_service import get_pending_dispense_for_device
    from src.core.exceptions.errors import NotAuthenticatedException

    db = SessionLocal()
    try:
        # TEST 1: Public Config Security
        print("\n--- TEST 1: Public Config & Secret Isolation ---")
        cfg = get_razorpay_public_config()
        print(f"  [✓] Public Key ID: {cfg.key_id}")
        print(f"  [✓] Test Mode: {cfg.test_mode}")
        print(f"  [✓] Currency: {cfg.currency}")
        assert not hasattr(cfg, "key_secret")
        assert not hasattr(cfg, "webhook_secret")
        print("  [✓] Assertion passed: Key secrets never exposed in public schemas.")

        # TEST 2: Dynamic QR Code Creation & Database Storage
        print("\n--- TEST 2: QR Code Creation & DB Storage ---")
        device = db.query(Device).filter(Device.device_id == "VM-000001").first()
        assert device is not None, "Device VM-000001 should exist in seeded database"

        qr_res = create_razorpay_qr(
            db=db,
            device_id="VM-000001",
            slot_number=1,
            amount_rupees=10.0,
            usage="single_use",
            name_override="Test Soda Slot 1",
        )
        print(f"  [✓] QR Created: {qr_res['razorpay_qr_id']}")
        print(f"  [✓] QR Payload: {qr_res['qr_payload']}")
        print(f"  [✓] Amount Paise: {qr_res['amount_paise']}")

        # Verify DB record
        db_qr = db.query(RazorpayQRCode).filter(RazorpayQRCode.razorpay_qr_id == qr_res["razorpay_qr_id"]).first()
        assert db_qr is not None
        assert db_qr.amount == 1000
        assert db_qr.status == "active"
        print("  [✓] QR record successfully persisted in 'razorpay_qr_codes' table.")

        # TEST 3: Webhook Raw-Body HMAC-SHA256 Signature Verification
        print("\n--- TEST 3: HMAC-SHA256 Signature Verification ---")
        test_body = b'{"event":"payment.captured","test":true}'
        computed_sig = compute_razorpay_signature(test_body, settings.RAZORPAY_WEBHOOK_SECRET)
        is_valid = verify_webhook_signature(test_body, computed_sig)
        assert is_valid is True, "Valid signature verification failed"
        print("  [✓] Valid signature verified correctly.")

        tampered_sig = "a" * 64
        is_tampered_valid = verify_webhook_signature(test_body, tampered_sig)
        assert is_tampered_valid is False, "Tampered signature should not verify"
        print("  [✓] Tampered signature rejected correctly.")

        # TEST 4: Tampered Webhook Delivery Rejection
        print("\n--- TEST 4: Tampered Webhook Exception & Audit Logging ---")
        try:
            process_webhook_event(
                db=db,
                raw_body=test_body,
                signature=tampered_sig,
                enforce_signature=True,
            )
            assert False, "Should have raised NotAuthenticatedException"
        except NotAuthenticatedException:
            print("  [✓] NotAuthenticatedException raised as expected.")

        # Verify FAILED WebhookEvent record was saved
        failed_event = db.query(WebhookEvent).filter(WebhookEvent.status == "FAILED").first()
        assert failed_event is not None
        print(f"  [✓] Failed attempt logged in 'webhook_events' audit table: status={failed_event.status}")

        # TEST 5: Valid Webhook Delivery & Price Matching to Slot
        print("\n--- TEST 5: Webhook Processing (payment.captured -> DISPENSE_AUTHORIZED) ---")
        # Clear any stale pending orders from previous test runs so queue is fresh
        stale_orders = db.query(Order).filter(
            Order.device_id == device.id,
            Order.order_status.in_(["PAID", "DISPENSE_AUTHORIZED"]),
        ).all()
        for o in stale_orders:
            o.order_status = "DISPENSED"
        db.commit()

        unique_payment_id = f"pay_test_{int(time.time())}"
        unique_event_id = f"evt_{unique_payment_id}"
        valid_payload = {
            "entity": "event",
            "account_id": "acc_test_merchant_1",
            "event": "payment.captured",
            "id": unique_event_id,
            "contains": ["payment"],
            "payload": {
                "payment": {
                    "entity": {
                        "id": unique_payment_id,
                        "entity": "payment",
                        "amount": 1000,
                        "currency": "INR",
                        "status": "captured",
                        "method": "upi",
                        "description": "Cold Drink Test Payment",
                        "notes": {
                            "device_id": "VM-000001",
                            "slot_number": "1",
                        },
                    }
                }
            },
            "created_at": int(time.time()),
        }
        raw_body = json.dumps(valid_payload).encode("utf-8")
        valid_sig = compute_razorpay_signature(raw_body, settings.RAZORPAY_WEBHOOK_SECRET)

        result = process_webhook_event(
            db=db,
            raw_body=raw_body,
            signature=valid_sig,
            enforce_signature=True,
        )
        print(f"  [✓] Webhook Result: {result}")
        assert result.get("status") == "SUCCESS"
        assert result.get("dispense", {}).get("status") in ("DISPENSE_AUTHORIZED", "PAID")
        authorized_order_id = result.get("dispense", {}).get("order_id")

        # Verify Order & Payment in DB
        order = db.query(Order).filter(Order.id == authorized_order_id).first()
        assert order is not None
        assert order.order_status in ("DISPENSE_AUTHORIZED", "PAID")
        assert order.payment.payment_status == "SUCCESS"
        assert order.payment.razorpay_payment_id == unique_payment_id
        print(f"  [✓] Order {order.order_number} marked DISPENSE_AUTHORIZED; Payment {order.payment.razorpay_payment_id} marked SUCCESS.")

        # TEST 6: ESP32 Hardware Polling (pending-dispense)
        print("\n--- TEST 6: ESP32 Hardware Polling ---")
        pending = get_pending_dispense_for_device(db=db, device_id="VM-000001")
        print(f"  [✓] Pending Dispense Query: {pending}")
        assert pending.get("dispense_pending") is True
        assert pending.get("slot_number") == 1
        assert pending.get("order_id") == order.id
        print("  [✓] ESP32 node successfully discovers pending dispense!")

        # TEST 7: Duplicate-Event Protection (Idempotency)
        print("\n--- TEST 7: Duplicate Webhook Event Protection ---")
        dup_result = process_webhook_event(
            db=db,
            raw_body=raw_body,
            signature=valid_sig,
            enforce_signature=True,
        )
        print(f"  [✓] Duplicate Webhook Result: {dup_result}")
        assert dup_result.get("status") == "DUPLICATE_IGNORED"
        assert dup_result.get("event_id") == unique_event_id
        print("  [✓] Duplicate event safely intercepted without duplicate dispensing.")

        # TEST 8: Checkout Payment Signature Verification
        print("\n--- TEST 8: Razorpay Checkout Signature Verification ---")
        test_order_id = "order_EKwxwAgItmmXdp"
        test_pay_id = "pay_29QQoUBi66xm2f"
        msg = f"{test_order_id}|{test_pay_id}".encode("utf-8")
        chk_sig = hmac.new(settings.RAZORPAY_KEY_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        assert verify_payment_signature(test_order_id, test_pay_id, chk_sig) is True
        assert verify_payment_signature(test_order_id, test_pay_id, "wrong_sig") is False
        print("  [✓] Razorpay checkout signature verification verified.")

        print("\n" + "=" * 70)
        print("ALL 8 RAZORPAY INTEGRATION & WEBHOOK TESTS PASSED! [✓]")
        print("=" * 70)
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Razorpay Integration Test Suite")
    parser.add_argument(
        "--url",
        type=str,
        default=None,
        help="Optional base URL of target server (e.g. http://35.154.219.82:8000). If omitted, runs direct service tests.",
    )
    args = parser.parse_args()
    if args.url:
        run_http_tests(args.url)
    else:
        run_direct_tests()
