"""
Comprehensive database seed script.
Populates standard device types, manufacturer super-admin, sample clients, devices,
modules, products, slots, employees, and RFID cards for development and verification.
"""
import hashlib
import json
import sys
import os
from datetime import datetime, timezone

# Set UTF-8 encoding for Windows console compatibility
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy.orm import Session
from src.core.config.settings import settings
from src.core.security.hashing import hash_password
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
    Employee,
    RFIDCard,
    AuditLog,
)


def seed_database(db: Session) -> None:
    """Execute complete initial database seeding."""
    print("🌱 Starting database seed...")

    # 1. Seed Device Types
    vending_type = db.query(DeviceType).filter_by(code="VENDING_MACHINE").first()
    if not vending_type:
        vending_type = DeviceType(
            code="VENDING_MACHINE",
            name="Commercial Vending Machine Controller",
            description="ESP32-based multi-payment vending controller with drop detection and spiral motor drivers.",
            supported_modules=["QR_PAYMENT", "COIN_PAYMENT", "RFID_ACCESS"],
            capability_schema={
                "max_slots": 60,
                "supported_payment_protocols": ["UPI_DYNAMIC_QR", "PULSE_COIN_ACCEPTOR", "MDB", "MIFARE_RFID"],
            },
        )
        db.add(vending_type)

    rfid_type = db.query(DeviceType).filter_by(code="RFID_ATTENDANCE").first()
    if not rfid_type:
        rfid_type = DeviceType(
            code="RFID_ATTENDANCE",
            name="Smart RFID Attendance Terminal",
            description="ESP32-based attendance terminal with offline card whitelist caching and direction logic.",
            supported_modules=["RFID_ACCESS", "OFFLINE_SYNC"],
            capability_schema={
                "card_technologies": ["MIFARE_13.56MHZ", "EM4100_125KHZ", "WIEGAND_26_34"],
                "max_offline_records": 10000,
            },
        )
        db.add(rfid_type)

    db.flush()
    print("  [✓] Device types seeded: VENDING_MACHINE, RFID_ATTENDANCE")

    # 2. Seed Manufacturer Super-Admin User
    superadmin = db.query(User).filter_by(username=settings.SUPERADMIN_USERNAME).first()
    if not superadmin:
        superadmin = User(
            client_id=None,  # Manufacturer has no client_id (global scope)
            username=settings.SUPERADMIN_USERNAME,
            email=settings.SUPERADMIN_EMAIL,
            password_hash=hash_password(settings.SUPERADMIN_PASSWORD),
            full_name="Platform Super Administrator",
            role="MANUFACTURER_ADMIN",
            status="ACTIVE",
        )
        db.add(superadmin)
        db.flush()
        print(f"  [✓] Manufacturer admin user created: {settings.SUPERADMIN_USERNAME}")

    # 3. Seed Demo Client Tenant
    demo_client = db.query(Client).filter_by(client_code="CLIENT_APEX").first()
    if not demo_client:
        demo_client = Client(
            client_code="CLIENT_APEX",
            name="Apex Tech Parks Pvt Ltd",
            contact_email="iot-fleet@apextech.local",
            contact_phone="+91-9876543210",
            status="ACTIVE",
            address="Building 4B, Cyber Gateway, Bangalore, Karnataka, India",
        )
        db.add(demo_client)
        db.flush()
        print("  [✓] Demo client created: Apex Tech Parks Pvt Ltd")

    # 4. Seed Client Admin User
    client_admin = db.query(User).filter_by(username="apex_admin").first()
    if not client_admin:
        client_admin = User(
            client_id=demo_client.id,
            username="apex_admin",
            email="admin@apextech.local",
            password_hash=hash_password("Apex@Admin2026!"),
            full_name="Arun Kumar (Client Ops)",
            role="CLIENT_ADMIN",
            status="ACTIVE",
        )
        db.add(client_admin)
        db.flush()
        print("  [✓] Client admin user created: apex_admin")

    # 5. Seed Products for Client
    coke = db.query(Product).filter_by(client_id=demo_client.id, product_code="BEV-COKE-300").first()
    if not coke:
        coke = Product(
            client_id=demo_client.id,
            product_code="BEV-COKE-300",
            name="Coca Cola Can 300ml",
            description="Chilled sparkling carbonated beverage.",
            price=4000,  # ₹40.00
            is_active=True,
        )
        db.add(coke)

    water = db.query(Product).filter_by(client_id=demo_client.id, product_code="BEV-WATER-500").first()
    if not water:
        water = Product(
            client_id=demo_client.id,
            product_code="BEV-WATER-500",
            name="Natural Spring Water 500ml",
            description="Pure mountain mineral water bottle.",
            price=2000,  # ₹20.00
            is_active=True,
        )
        db.add(water)

    chips = db.query(Product).filter_by(client_id=demo_client.id, product_code="SNK-CHIPS-50").first()
    if not chips:
        chips = Product(
            client_id=demo_client.id,
            product_code="SNK-CHIPS-50",
            name="Classic Salted Potato Chips 50g",
            description="Crispy salted potato crisps.",
            price=3000,  # ₹30.00
            is_active=True,
        )
        db.add(chips)

    db.flush()
    print("  [✓] Client products seeded: Coke (₹40), Water (₹20), Chips (₹30)")

    # 6. Seed Vending Machine Devices with Different Module Combinations
    device_configs = [
        ("VM-000001", "HW-ESP32S3-V1.2", "ESP32-S3-0x3C8427F8B101", "3C:84:27:F8:B1:01", "MFG-2026-VM-001", True, False, False),
        ("VM-000002", "HW-ESP32S3-V1.2", "ESP32-S3-0x3C8427F8B102", "3C:84:27:F8:B1:02", "MFG-2026-VM-002", False, True, False),
        ("VM-000003", "HW-ESP32S3-V1.2", "ESP32-S3-0x3C8427F8B103", "3C:84:27:F8:B1:03", "MFG-2026-VM-003", True, True, False),
    ]

    for dev_id, hw_id, chip, mac, serial, qr_on, coin_on, rfid_on in device_configs:
        dev = db.query(Device).filter_by(device_id=dev_id).first()
        if not dev:
            dev = Device(
                device_id=dev_id,
                client_id=demo_client.id,
                device_type_id=vending_type.id,
                hardware_id=hw_id,
                chip_id=chip,
                mac_address=mac,
                factory_serial=serial,
                status="ACTIVE",
                is_online=True,
                current_firmware_version="v1.0.0",
                current_config_version=1,
            )
            db.add(dev)
            db.flush()

            # Modules
            db.add(DeviceModule(device_id=dev.id, module_code="QR_PAYMENT", is_enabled=qr_on))
            db.add(DeviceModule(device_id=dev.id, module_code="COIN_PAYMENT", is_enabled=coin_on))
            db.add(DeviceModule(device_id=dev.id, module_code="RFID_ACCESS", is_enabled=rfid_on))

            # Credentials
            db.add(DeviceCredential(
                device_id=dev.id,
                auth_type="TOKEN",
                token_hash=hashlib.sha256(f"dev_token_{dev_id}".encode()).hexdigest(),
            ))

            # Slots
            slot1 = MachineSlot(
                device_id=dev.id,
                client_id=demo_client.id,
                slot_number=1,
                slot_code="SLOT-01",
                product_id=water.id,
                capacity=15,
                current_stock=12,
                motor_pin=18,
                pulse_duration_ms=600,
            )
            slot2 = MachineSlot(
                device_id=dev.id,
                client_id=demo_client.id,
                slot_number=2,
                slot_code="SLOT-02",
                product_id=coke.id,
                capacity=15,
                current_stock=10,
                motor_pin=19,
                pulse_duration_ms=600,
            )
            slot3 = MachineSlot(
                device_id=dev.id,
                client_id=demo_client.id,
                slot_number=3,
                slot_code="SLOT-03",
                product_id=chips.id,
                capacity=10,
                current_stock=8,
                motor_pin=21,
                pulse_duration_ms=500,
            )
            db.add_all([slot1, slot2, slot3])

            # Initial Device Config (Version 1)
            cfg_payload = {
                "device_id": dev_id,
                "config_version": 1,
                "modules": {
                    "QR_PAYMENT": qr_on,
                    "COIN_PAYMENT": coin_on,
                    "RFID_ACCESS": rfid_on,
                },
                "slots": [
                    {"slot": 1, "code": "SLOT-01", "product": "BEV-WATER-500", "price": 2000, "pin": 18},
                    {"slot": 2, "code": "SLOT-02", "product": "BEV-COKE-300", "price": 4000, "pin": 19},
                    {"slot": 3, "code": "SLOT-03", "product": "SNK-CHIPS-50", "price": 3000, "pin": 21},
                ],
            }
            payload_str = json.dumps(cfg_payload, sort_keys=True)
            checksum = hashlib.sha256(payload_str.encode()).hexdigest()

            db.add(DeviceConfig(
                device_id=dev.id,
                client_id=demo_client.id,
                active_version=1,
                config_payload=cfg_payload,
                checksum=checksum,
                is_synced=True,
            ))
            db.add(ConfigurationVersion(
                device_id=dev.id,
                client_id=demo_client.id,
                version_number=1,
                config_payload=cfg_payload,
                checksum=checksum,
                change_reason="Factory initial provisioning",
                created_by_user_id=superadmin.id,
            ))

    print("  [✓] Vending Machines seeded: VM-000001 (QR), VM-000002 (Coin), VM-000003 (Hybrid)")

    # 7. Seed RFID Attendance Terminal
    rfid_dev = db.query(Device).filter_by(device_id="RFID-000001").first()
    if not rfid_dev:
        rfid_dev = Device(
            device_id="RFID-000001",
            client_id=demo_client.id,
            device_type_id=rfid_type.id,
            hardware_id="HW-ESP32-RFID-V1.0",
            chip_id="ESP32-D0WD-0x5C8427A1B201",
            mac_address="5C:84:27:A1:B2:01",
            factory_serial="MFG-2026-RFID-001",
            status="ACTIVE",
            is_online=True,
            current_firmware_version="v1.0.0",
            current_config_version=1,
        )
        db.add(rfid_dev)
        db.flush()

        db.add(DeviceModule(device_id=rfid_dev.id, module_code="RFID_ACCESS", is_enabled=True))
        db.add(DeviceModule(device_id=rfid_dev.id, module_code="OFFLINE_SYNC", is_enabled=True))

        db.add(DeviceCredential(
            device_id=rfid_dev.id,
            auth_type="TOKEN",
            token_hash=hashlib.sha256("dev_token_RFID-000001".encode()).hexdigest(),
        ))

        rfid_cfg = {
            "device_id": "RFID-000001",
            "config_version": 1,
            "reader_mode": "DIRECTIONAL_TOGGLE",
            "buzzer_beep_ms": 100,
            "offline_cache_enabled": True,
        }
        rfid_str = json.dumps(rfid_cfg, sort_keys=True)
        rfid_chk = hashlib.sha256(rfid_str.encode()).hexdigest()

        db.add(DeviceConfig(
            device_id=rfid_dev.id,
            client_id=demo_client.id,
            active_version=1,
            config_payload=rfid_cfg,
            checksum=rfid_chk,
            is_synced=True,
        ))
        db.add(ConfigurationVersion(
            device_id=rfid_dev.id,
            client_id=demo_client.id,
            version_number=1,
            config_payload=rfid_cfg,
            checksum=rfid_chk,
            change_reason="Factory initial provisioning",
            created_by_user_id=superadmin.id,
        ))

    print("  [✓] RFID Terminal seeded: RFID-000001")

    # 8. Seed Employees and RFID Cards (Demonstrating card lifecycle & replacement lineage)
    emp1 = db.query(Employee).filter_by(client_id=demo_client.id, employee_code="EMP001").first()
    if not emp1:
        emp1 = Employee(
            client_id=demo_client.id,
            employee_code="EMP001",
            full_name="Arun Kumar",
            department="Engineering",
            designation="Principal Embedded Architect",
            email="arun.kumar@apextech.local",
            status="ACTIVE",
        )
        db.add(emp1)
        db.flush()

        # Old card (replaced)
        old_card = RFIDCard(
            client_id=demo_client.id,
            employee_id=emp1.id,
            card_uid="04:A3:92:7B:11:65",
            status="REPLACED",
            revocation_reason="Damaged chip, superseded by new card",
        )
        db.add(old_card)
        db.flush()

        # New active replacement card
        new_card = RFIDCard(
            client_id=demo_client.id,
            employee_id=emp1.id,
            card_uid="04:B5:12:8C:33:99",
            status="ACTIVE",
            replacement_card_id=old_card.id,
        )
        db.add(new_card)

    emp2 = db.query(Employee).filter_by(client_id=demo_client.id, employee_code="EMP002").first()
    if not emp2:
        emp2 = Employee(
            client_id=demo_client.id,
            employee_code="EMP002",
            full_name="Priya Sharma",
            department="Operations",
            designation="Fleet Manager",
            email="priya.sharma@apextech.local",
            status="ACTIVE",
        )
        db.add(emp2)
        db.flush()

        card2 = RFIDCard(
            client_id=demo_client.id,
            employee_id=emp2.id,
            card_uid="04:D8:44:9E:55:12",
            status="ACTIVE",
        )
        db.add(card2)

    emp3_blocked = db.query(Employee).filter_by(client_id=demo_client.id, employee_code="EMP003").first()
    if not emp3_blocked:
        emp3_blocked = Employee(
            client_id=demo_client.id,
            employee_code="EMP003",
            full_name="Rohan Verma",
            department="Security",
            designation="Technician",
            status="TERMINATED",
        )
        db.add(emp3_blocked)
        db.flush()

        card3 = RFIDCard(
            client_id=demo_client.id,
            employee_id=emp3_blocked.id,
            card_uid="04:EE:77:1A:88:44",
            status="BLOCKED",
            revocation_reason="Employee departed company",
        )
        db.add(card3)

    print("  [✓] Employees & RFID cards seeded (demonstrating ACTIVE, REPLACED, and BLOCKED lifecycle)")

    # 9. Seed Audit Log Record
    db.add(AuditLog(
        client_id=demo_client.id,
        user_id=superadmin.id,
        action="DATABASE_SEED",
        entity_type="SYSTEM",
        entity_id="ROOT",
        new_state={"status": "INITIAL_SEED_COMPLETE", "devices_count": 4},
        ip_address="127.0.0.1",
        user_agent="SeedScript/1.0",
    ))

    db.commit()
    print("✅ Database seeding completed successfully!")


if __name__ == "__main__":
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_database(session)
    finally:
        session.close()
