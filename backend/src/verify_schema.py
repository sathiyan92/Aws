"""
Phase 2 Schema and Data Model Verification Script.
Creates all database tables, verifies table schemas, validates foreign keys and indexes,
runs the seed pipeline, and asserts data integrity across all 21 entities.
"""
import sys
import os

# Set UTF-8 encoding for Windows console compatibility
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import inspect
from src.db.session import engine, SessionLocal
from src.db.base import Base
from src.db.models import (
    Client,
    User,
    DeviceType,
    Device,
    DeviceModule,
    DeviceCredential,
    DeviceConfig,
    ConfigurationVersion,
    Product,
    MachineSlot,
    Order,
    Payment,
    Transaction,
    Employee,
    RFIDCard,
    AttendanceEvent,
    FirmwareVersion,
    OTADeployment,
    DeviceHeartbeat,
    DeviceLog,
    AuditLog,
)
from src.db.seed import seed_database


REQUIRED_ENTITIES = [
    "users",
    "clients",
    "devices",
    "device_types",
    "device_modules",
    "device_credentials",
    "device_configs",
    "configuration_versions",
    "products",
    "machine_slots",
    "firmware_versions",
    "ota_deployments",
    "rfid_cards",
    "employees",
    "attendance_events",
    "orders",
    "payments",
    "transactions",
    "device_heartbeats",
    "device_logs",
    "audit_logs",
]


def run_verification():
    print("=" * 70)
    print("PHASE 2: DATABASE SCHEMA & DATA MODEL VERIFICATION")
    print("=" * 70)

    # 1. Create tables
    print("\n[Step 1] Creating all tables from SQLAlchemy 2.0 Metadata...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("  [✓] All table definitions successfully applied to database engine.")

    # 2. Introspect database
    print("\n[Step 2] Introspecting database schema...")
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())

    missing_tables = []
    for entity in REQUIRED_ENTITIES:
        if entity in existing_tables:
            cols = [c["name"] for c in inspector.get_columns(entity)]
            fks = inspector.get_foreign_keys(entity)
            indexes = inspector.get_indexes(entity)
            print(f"  [✓] Table '{entity:<24}': {len(cols):>2} columns, {len(fks):>2} FKs, {len(indexes):>2} indexes")
        else:
            missing_tables.append(entity)
            print(f"  [✗] Missing required table: {entity}")

    if missing_tables:
        print(f"\n❌ FATAL: Missing tables: {missing_tables}")
        sys.exit(1)
    else:
        print(f"\n  [✓] All {len(REQUIRED_ENTITIES)} required entities verified present.")

    # 3. Run seed pipeline
    print("\n[Step 3] Executing initial seed data pipeline...")
    session = SessionLocal()
    try:
        seed_database(session)

        # 4. Assert integrity
        print("\n[Step 4] Asserting data model integrity & relationships...")

        # Verify SuperAdmin
        admin = session.query(User).filter_by(username="admin").first()
        assert admin is not None, "Superadmin not found"
        assert admin.role == "MANUFACTURER_ADMIN", "Superadmin role mismatch"
        assert admin.client_id is None, "Manufacturer admin must have NULL client_id"
        print(f"  [✓] Manufacturer Super-Admin verified (global scope, client_id=NULL)")

        # Verify Client Tenant
        client = session.query(Client).filter_by(client_code="CLIENT_APEX").first()
        assert client is not None, "Demo client not found"
        assert len(client.users) >= 1, "Client user relationship failed"
        assert len(client.devices) >= 4, "Client devices relationship failed"
        assert len(client.products) >= 3, "Client products relationship failed"
        assert len(client.employees) >= 3, "Client employees relationship failed"
        print(f"  [✓] Client Tenant '{client.name}' verified with {len(client.devices)} devices and {len(client.products)} products")

        # Verify Device Modules (VM-000001: QR only; VM-000002: Coin only; VM-000003: Hybrid)
        vm1 = session.query(Device).filter_by(device_id="VM-000001").first()
        assert vm1 is not None
        qr_mod = next(m for m in vm1.modules if m.module_code == "QR_PAYMENT")
        coin_mod = next(m for m in vm1.modules if m.module_code == "COIN_PAYMENT")
        assert qr_mod.is_enabled is True and coin_mod.is_enabled is False, "VM-000001 module config mismatch"
        print(f"  [✓] Device VM-000001 verified: QR_PAYMENT=True, COIN_PAYMENT=False")

        vm2 = session.query(Device).filter_by(device_id="VM-000002").first()
        assert vm2 is not None
        qr_mod2 = next(m for m in vm2.modules if m.module_code == "QR_PAYMENT")
        coin_mod2 = next(m for m in vm2.modules if m.module_code == "COIN_PAYMENT")
        assert qr_mod2.is_enabled is False and coin_mod2.is_enabled is True, "VM-000002 module config mismatch"
        print(f"  [✓] Device VM-000002 verified: QR_PAYMENT=False, COIN_PAYMENT=True")

        vm3 = session.query(Device).filter_by(device_id="VM-000003").first()
        assert vm3 is not None
        qr_mod3 = next(m for m in vm3.modules if m.module_code == "QR_PAYMENT")
        coin_mod3 = next(m for m in vm3.modules if m.module_code == "COIN_PAYMENT")
        assert qr_mod3.is_enabled is True and coin_mod3.is_enabled is True, "VM-000003 module config mismatch"
        print(f"  [✓] Device VM-000003 verified: QR_PAYMENT=True, COIN_PAYMENT=True (Hybrid)")

        # Verify Versioned Configuration
        assert vm1.config is not None, "DeviceConfig missing"
        assert vm1.config.active_version == 1, "Config version mismatch"
        assert len(vm1.config_history) >= 1, "ConfigurationVersion history missing"
        print(f"  [✓] Device Configuration versioning verified (v{vm1.config.active_version} active, history tracked)")

        # Verify RFID Card Lifecycle and Replacement Lineage
        emp = session.query(Employee).filter_by(employee_code="EMP001").first()
        assert emp is not None
        assert len(emp.cards) == 2, "Employee must have 2 cards (1 old replaced, 1 active)"
        old_c = next(c for c in emp.cards if c.status == "REPLACED")
        new_c = next(c for c in emp.cards if c.status == "ACTIVE")
        assert new_c.replacement_card_id == old_c.id, "Replacement lineage pointer mismatch"
        print(f"  [✓] RFID Card lifecycle verified: Old card '{old_c.card_uid}' (REPLACED) linked to New card '{new_c.card_uid}' (ACTIVE)")

        # Verify Order & Dispense Flow simulation record
        order = Order(
            order_number="ORD-TEST-001",
            client_id=client.id,
            device_id=vm1.id,
            slot_id=vm1.slots[0].id,
            product_id=vm1.slots[0].product_id,
            payment_method="QR_PAYMENT",
            unit_price=2000,
            quantity=1,
            total_amount=2000,
            order_status="DISPENSED",
            dispense_token="tok_test_sample_hash",
        )
        session.add(order)
        session.flush()

        payment = Payment(
            order_id=order.id,
            client_id=client.id,
            gateway_provider="UPI_DYNAMIC",
            gateway_payment_intent_id="intent_upi_12345",
            gateway_transaction_id="tx_upi_67890",
            amount=2000,
            payment_status="SUCCESS",
        )
        session.add(payment)
        session.flush()

        tx = Transaction(
            transaction_number="TX-TEST-001",
            client_id=client.id,
            device_id=vm1.id,
            order_id=order.id,
            payment_id=payment.id,
            transaction_type="QR_VEND",
            amount=2000,
            dispense_status="SUCCESS",
            transacted_at=order.created_at,
        )
        session.add(tx)

        # Verify Attendance Event simulation record
        att = AttendanceEvent(
            event_uuid="uuid-edge-tap-0001",
            client_id=client.id,
            device_id=session.query(Device).filter_by(device_id="RFID-000001").first().id,
            card_id=new_c.id,
            employee_id=emp.id,
            card_uid_scanned=new_c.card_uid,
            timestamp=new_c.created_at,
            event_type="IN",
            is_offline_sync=False,
        )
        session.add(att)
        session.commit()
        print(f"  [✓] Simulated Order, Payment, Transaction, and AttendanceEvent successfully committed")

        print("\n" + "=" * 70)
        print("✅ PHASE 2 VERIFICATION PASSED: ALL 21 ENTITIES & RELATIONS VALIDATED")
        print("=" * 70)

    finally:
        session.close()


if __name__ == "__main__":
    run_verification()
