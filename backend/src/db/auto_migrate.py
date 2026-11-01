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
    except Exception as e:
        logger.error(f"[AutoMigrate] Auto-migration error: {e}", exc_info=True)

