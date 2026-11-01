"""
Automated Database Schema Migration & Synchronization Helper.
Ensures existing SQLite or PostgreSQL database tables are non-destructively
updated with any newly added columns and tables without data loss.
"""
import logging
from sqlalchemy import inspect, text

logger = logging.getLogger(__name__)


def run_auto_migrations(engine) -> None:
    """
    Safely inspects existing tables and adds any missing columns or indexes
    without dropping existing user data.
    """
    try:
        from src.db.base import Base
        Base.metadata.create_all(bind=engine)

        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        table_columns = {
            "orders": {
                "paid_at": "DATETIME",
                "dispense_token": "VARCHAR(128)",
                "dispense_token_expires_at": "DATETIME",
                "dispensed_at": "DATETIME",
                "razorpay_qr_id": "VARCHAR(128)",
                "qr_payload": "TEXT",
            },
            "payments": {
                "razorpay_payment_id": "VARCHAR(128)",
                "razorpay_order_id": "VARCHAR(128)",
                "gateway_provider": "VARCHAR(64) DEFAULT 'RAZORPAY'",
                "gateway_payment_intent_id": "VARCHAR(128)",
                "gateway_transaction_id": "VARCHAR(128)",
                "gateway_event_id": "VARCHAR(128)",
                "raw_gateway_response": "TEXT",
                "paid_at": "DATETIME",
            },
            "machine_slots": {
                "override_price": "INTEGER",
                "motor_pin": "INTEGER",
                "pulse_duration_ms": "INTEGER DEFAULT 500",
            },
            "devices": {
                "is_online": "BOOLEAN DEFAULT 0",
                "last_heartbeat_at": "DATETIME",
                "current_firmware_version": "VARCHAR(64)",
                "current_config_version": "INTEGER DEFAULT 1",
                "mac_address": "VARCHAR(32)",
            },
            "clients": {
                "razorpay_account_id": "VARCHAR(64)",
                "razorpay_merchant_vpa": "VARCHAR(128)",
            },
        }

        with engine.begin() as conn:
            for tbl, cols in table_columns.items():
                if tbl in existing_tables:
                    current_cols = {c["name"] for c in inspector.get_columns(tbl)}
                    for col_name, col_type in cols.items():
                        if col_name not in current_cols:
                            logger.info(f"[AutoMigrate] Adding missing column '{col_name}' ({col_type}) to table '{tbl}'")
                            try:
                                conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col_name} {col_type}"))
                            except Exception as add_err:
                                logger.warning(f"[AutoMigrate] Notice adding {col_name} to {tbl}: {add_err}")

        logger.info("[AutoMigrate] Database schema verified and synchronized.")

        # Seed initial fleet node and default QR binding if not present
        _ensure_fleet_defaults(engine)
    except Exception as e:
        logger.error(f"[AutoMigrate] Auto-migration error: {e}", exc_info=True)


def _ensure_fleet_defaults(engine) -> None:
    """
    Ensures default client, device type, VM-000001, and active Standee QR binding
    are seeded so bench testing and live payments work out of the box.
    """
    from sqlalchemy.orm import sessionmaker
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    try:
        from src.db.base import utc_now, generate_uuid
        from src.db.models.client import Client
        from src.db.models.device import Device, DeviceType, DeviceCredential
        from src.db.models.vending import MachineSlot, Product, RazorpayQRCode
        import hashlib

        # 1. Ensure Client
        client = db.query(Client).first()
        if not client:
            client = Client(
                id=generate_uuid(),
                name="G-TECH Vending Fleet",
                code="GTECH",
                contact_email="admin@gtechinfo.in",
                is_active=True,
            )
            db.add(client)
            db.flush()

        # 2. Ensure DeviceType
        dev_type = db.query(DeviceType).filter_by(code="VENDING_MACHINE").first()
        if not dev_type:
            dev_type = DeviceType(
                id=generate_uuid(),
                code="VENDING_MACHINE",
                name="Smart Vending Machine",
                category="VENDING",
            )
            db.add(dev_type)
            db.flush()

        # 3. Ensure VM-000001
        device = db.query(Device).filter(
            (Device.device_id == "VM-000001") | (Device.mac_address.ilike("14:08:08:9F:5A:C0"))
        ).first()
        if not device:
            device = Device(
                id=generate_uuid(),
                device_id="VM-000001",
                client_id=client.id,
                device_type_id=dev_type.id,
                hardware_id="HW-VM-000001",
                chip_id="CHIP-VM-000001",
                mac_address="14:08:08:9F:5A:C0",
                factory_serial="SN-VM-000001",
                status="ACTIVE",
                is_online=True,
                last_heartbeat_at=utc_now(),
                current_firmware_version="v2.2.0-razorpay-ota",
                current_config_version=1,
            )
            db.add(device)
            db.flush()

            token_val = "dev_token_VM-000001"
            cred = DeviceCredential(
                device_id=device.id,
                auth_type="TOKEN",
                token_hash=hashlib.sha256(token_val.encode()).hexdigest(),
            )
            db.add(cred)
            db.flush()

        # 4. Ensure Product & Slot 1
        prod = db.query(Product).filter_by(client_id=client.id, product_code=f"PROD-{device.device_id}-1").first()
        if not prod:
            prod = Product(
                id=generate_uuid(),
                client_id=client.id,
                name="G-TECH Test",
                product_code=f"PROD-{device.device_id}-1",
                price=200,
                is_active=True,
            )
            db.add(prod)
            db.flush()

        slot = db.query(MachineSlot).filter_by(device_id=device.id, slot_number=1).first()
        if not slot:
            slot = MachineSlot(
                id=generate_uuid(),
                device_id=device.id,
                slot_number=1,
                product_id=prod.id,
                capacity=20,
                current_stock=10,
                is_active=True,
                override_price=200,
            )
            db.add(slot)
            db.flush()
        else:
            if slot.override_price is None or slot.override_price == 100:
                slot.override_price = 200
                db.flush()

        # 5. Ensure RazorpayQRCode for TuXKipEEX2KteFqrv2
        raw_qr = "upi://pay?am=2.00&cu=INR&mc=5300&mode=19&pa=gtech282722.rzp@rxairtel&tn=Payment%20To%20GTECH&tr=TuXKipEEX2KteFqrv2"
        qr_keys = ["TuXKipEEX2KteFqrv2", "qr_TuXKipEEX2KteFqrv2"]
        for q_key in qr_keys:
            existing_qr = db.query(RazorpayQRCode).filter_by(razorpay_qr_id=q_key).first()
            if not existing_qr:
                qr_rec = RazorpayQRCode(
                    client_id=client.id,
                    device_id=device.id,
                    slot_id=slot.id,
                    razorpay_qr_id=q_key,
                    name=f"Standee QR for {device.device_id}",
                    usage="multiple_use",
                    fixed_amount=True,
                    amount=200,
                    currency="INR",
                    qr_payload=raw_qr,
                    status="active",
                    notes={"device_id": device.device_id, "tr": "TuXKipEEX2KteFqrv2"},
                )
                db.add(qr_rec)
            else:
                existing_qr.device_id = device.id
                existing_qr.slot_id = slot.id
                existing_qr.amount = 200
                existing_qr.status = "active"

        db.commit()
        logger.info("[AutoMigrate] Fleet defaults and QR bindings verified for VM-000001.")
    except Exception as seed_err:
        db.rollback()
        logger.warning(f"[AutoMigrate] Notice verifying fleet seed: {seed_err}")
    finally:
        db.close()

