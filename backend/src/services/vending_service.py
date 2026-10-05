"""
Vending Machine Subsystem Business Logic Service.
Handles Product catalog management, slot assignments, live stock level tracking,
and automated configuration synchronization when product prices or slot configs change.
"""
from typing import List, Optional, Dict, Any, Tuple
from sqlalchemy.orm import Session
from src.db.base import utc_now
from src.db.models.vending import Product, MachineSlot
from src.db.models.device import Device
from src.db.models.client import Client
from src.db.models.audit import AuditLog
from src.core.exceptions.errors import (
    NotFoundException,
    BadRequestException,
    ForbiddenException,
)
from src.api.v1.vending.schemas import (
    ProductCreateRequest,
    ProductUpdateRequest,
    MachineSlotConfigureRequest,
    MachineSlotBulkItem,
)
from src.services.config_service import (
    build_device_composite_payload,
    sync_device_config_record,
)


def list_products(
    db: Session,
    client_id: Optional[str] = None,
    is_manufacturer: bool = False,
    active_only: bool = False,
) -> List[Product]:
    """
    List products belonging to the client tenant organization.
    Manufacturer admins can filter by client_id or view all products.
    """
    query = db.query(Product)
    if not is_manufacturer or client_id:
        if not client_id:
            return []
        query = query.filter(Product.client_id == client_id)

    if active_only:
        query = query.filter(Product.is_active == True)

    return query.order_by(Product.name.asc()).all()


def get_product(
    db: Session,
    product_id: str,
    client_id: Optional[str] = None,
    is_manufacturer: bool = False,
) -> Product:
    """
    Retrieve single catalog product with strict multi-tenant authorization.
    """
    product = db.query(Product).filter(
        (Product.id == product_id) | (Product.product_code == product_id)
    ).first()
    if not product:
        raise NotFoundException("Product", product_id)

    if not is_manufacturer and product.client_id != client_id:
        raise ForbiddenException(f"Access to product '{product.product_code}' of another tenant is prohibited.")

    return product


def create_product(
    db: Session,
    client_id: str,
    payload: ProductCreateRequest,
    actor_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Product:
    """
    Register a new product in the client tenant catalog.
    Enforces uniqueness of product_code per client.
    """
    client = db.query(Client).filter_by(id=client_id).first()
    if not client:
        raise NotFoundException("Client", client_id)

    existing = db.query(Product).filter(
        Product.client_id == client_id,
        Product.product_code == payload.product_code.strip().upper(),
    ).first()
    if existing:
        raise BadRequestException(f"Product with code '{payload.product_code}' already exists for this client.")

    product = Product(
        client_id=client_id,
        product_code=payload.product_code.strip().upper(),
        name=payload.name.strip(),
        description=payload.description,
        price=payload.price,
        image_url=payload.image_url,
        is_active=payload.is_active,
    )
    db.add(product)
    db.flush()

    db.add(AuditLog(
        client_id=client_id,
        user_id=actor_user_id,
        action="PRODUCT_CREATED",
        entity_type="PRODUCT",
        entity_id=product.id,
        new_state={
            "product_code": product.product_code,
            "name": product.name,
            "price": product.price,
            "client_id": client_id,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.commit()
    db.refresh(product)
    return product


def update_product(
    db: Session,
    product_id: str,
    payload: ProductUpdateRequest,
    client_id: Optional[str] = None,
    is_manufacturer: bool = False,
    actor_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Tuple[Product, int]:
    """
    Update catalog product attributes.
    PRICE UPDATE ENGINE:
    If product price changes, all vending machines with slots assigned to this product
    automatically receive configuration version bumps, new SHA-256 checksums, and MQTT alerts.
    Returns (updated_product, count_of_affected_machines).
    """
    product = get_product(db, product_id, client_id, is_manufacturer)
    old_price = product.price
    price_changed = (payload.price is not None and payload.price != old_price)

    if payload.name is not None:
        product.name = payload.name.strip()
    if payload.description is not None:
        product.description = payload.description
    if payload.price is not None:
        product.price = payload.price
    if payload.image_url is not None:
        product.image_url = payload.image_url
    if payload.is_active is not None:
        product.is_active = payload.is_active

    affected_machines_count = 0

    # If price changed, propagate to all assigned vending machines
    if price_changed:
        # Find slots referencing this product without slot-specific override
        slots_to_update = db.query(MachineSlot).filter(
            MachineSlot.product_id == product.id,
            MachineSlot.override_price == None,
        ).all()

        affected_device_ids = {s.device_id for s in slots_to_update}

        for dev_pk in affected_device_ids:
            device = db.query(Device).filter_by(id=dev_pk).first()
            if device:
                # Rebuild composite configuration payload with updated price
                composite_payload = build_device_composite_payload(device)
                change_reason = (
                    f"Product '{product.product_code}' price changed from "
                    f"₹{old_price/100:.2f} to ₹{product.price/100:.2f}"
                )
                sync_device_config_record(
                    db=db,
                    device=device,
                    raw_payload=composite_payload,
                    change_reason=change_reason,
                    actor_user_id=actor_user_id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                affected_machines_count += 1

    db.add(AuditLog(
        client_id=product.client_id,
        user_id=actor_user_id,
        action="PRODUCT_UPDATED",
        entity_type="PRODUCT",
        entity_id=product.id,
        old_state={"price": old_price},
        new_state={"price": product.price, "affected_machines": affected_machines_count},
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.commit()
    db.refresh(product)
    return product, affected_machines_count


def delete_product(
    db: Session,
    product_id: str,
    client_id: Optional[str] = None,
    is_manufacturer: bool = False,
    actor_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> None:
    """
    Remove product from catalog. Rejects if active slots currently reference it.
    """
    product = get_product(db, product_id, client_id, is_manufacturer)

    active_slot = db.query(MachineSlot).filter(
        MachineSlot.product_id == product.id,
        MachineSlot.is_active == True,
    ).first()
    if active_slot:
        raise BadRequestException(
            f"Cannot delete product '{product.product_code}' because slot {active_slot.slot_code} "
            f"on machine is actively assigned to it. Unassign or deactivate slot first."
        )

    db.add(AuditLog(
        client_id=product.client_id,
        user_id=actor_user_id,
        action="PRODUCT_DELETED",
        entity_type="PRODUCT",
        entity_id=product.id,
        old_state={"product_code": product.product_code, "name": product.name},
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.delete(product)
    db.commit()


# ==============================================================================
# MACHINE SLOT MANAGEMENT
# ==============================================================================

def list_machine_slots(db: Session, device: Device) -> List[MachineSlot]:
    """Retrieve all physical slots configured on a vending machine."""
    return db.query(MachineSlot).filter(
        MachineSlot.device_id == device.id
    ).order_by(MachineSlot.slot_number.asc()).all()


def configure_slot(
    db: Session,
    device: Device,
    slot_number: int,
    payload: MachineSlotConfigureRequest,
    actor_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> MachineSlot:
    """
    Configure or reassign a physical vending machine dispensing slot.
    Automatically rebuilds active configuration payload, increments version,
    and publishes to MQTT.
    """
    slot = db.query(MachineSlot).filter(
        MachineSlot.device_id == device.id,
        MachineSlot.slot_number == slot_number,
    ).first()

    if not slot:
        slot = MachineSlot(
            device_id=device.id,
            client_id=device.client_id,
            slot_number=slot_number,
            slot_code=f"SLOT-{slot_number:02d}",
        )
        db.add(slot)

    # Validate product if provided
    if payload.product_id:
        product = db.query(Product).filter_by(id=payload.product_id).first()
        if not product:
            raise NotFoundException("Product", payload.product_id)
        if product.client_id != device.client_id:
            raise ForbiddenException("Cannot assign a product from a different client tenant organization.")
        slot.product_id = product.id
    elif payload.product_id == "":
        slot.product_id = None

    if payload.override_price is not None:
        slot.override_price = payload.override_price if payload.override_price > 0 else None
    if payload.motor_pin is not None:
        slot.motor_pin = payload.motor_pin
    if payload.pulse_duration_ms is not None:
        slot.pulse_duration_ms = payload.pulse_duration_ms
    if payload.capacity is not None:
        slot.capacity = payload.capacity
    if payload.current_stock is not None:
        slot.current_stock = payload.current_stock
    if payload.is_active is not None:
        slot.is_active = payload.is_active

    db.flush()

    # Rebuild composite configuration payload
    composite = build_device_composite_payload(device)
    change_reason = f"Slot {slot.slot_code} reconfigured"

    sync_device_config_record(
        db=db,
        device=device,
        raw_payload=composite,
        change_reason=change_reason,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    db.commit()
    db.refresh(slot)
    return slot


def bulk_configure_slots(
    db: Session,
    device: Device,
    slots_items: List[MachineSlotBulkItem],
    actor_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> List[MachineSlot]:
    """
    Configure all slots on a vending machine in a single batch operation.
    Generates a single configuration version increment.
    """
    configured_slots = []
    for item in slots_items:
        slot = db.query(MachineSlot).filter(
            MachineSlot.device_id == device.id,
            MachineSlot.slot_number == item.slot_number,
        ).first()

        if not slot:
            slot = MachineSlot(
                device_id=device.id,
                client_id=device.client_id,
                slot_number=item.slot_number,
                slot_code=f"SLOT-{item.slot_number:02d}",
            )
            db.add(slot)

        if item.product_id:
            prod = db.query(Product).filter_by(id=item.product_id).first()
            if prod:
                slot.product_id = prod.id
        elif item.product_id == "":
            slot.product_id = None

        if item.override_price is not None:
            slot.override_price = item.override_price if item.override_price > 0 else None
        if item.motor_pin is not None:
            slot.motor_pin = item.motor_pin
        if item.pulse_duration_ms is not None:
            slot.pulse_duration_ms = item.pulse_duration_ms
        if item.capacity is not None:
            slot.capacity = item.capacity
        if item.current_stock is not None:
            slot.current_stock = item.current_stock
        if item.is_active is not None:
            slot.is_active = item.is_active

        configured_slots.append(slot)

    db.flush()

    # Rebuild composite configuration payload
    composite = build_device_composite_payload(device)
    change_reason = f"Batch reconfigured {len(slots_items)} slots"

    sync_device_config_record(
        db=db,
        device=device,
        raw_payload=composite,
        change_reason=change_reason,
        actor_user_id=actor_user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    db.commit()
    for s in configured_slots:
        db.refresh(s)
    return configured_slots


def restock_slot(
    db: Session,
    device: Device,
    slot_number: int,
    quantity_added: Optional[int] = None,
    new_stock_level: Optional[int] = None,
    actor_user_id: Optional[str] = None,
) -> MachineSlot:
    """
    Record stock replenishment for a vending slot without triggering a firmware config bump.
    """
    slot = db.query(MachineSlot).filter(
        MachineSlot.device_id == device.id,
        MachineSlot.slot_number == slot_number,
    ).first()
    if not slot:
        raise NotFoundException(f"Slot {slot_number} on device", device.device_id)

    old_stock = slot.current_stock
    if new_stock_level is not None:
        slot.current_stock = min(new_stock_level, slot.capacity)
    elif quantity_added is not None:
        slot.current_stock = min(slot.current_stock + quantity_added, slot.capacity)

    db.add(AuditLog(
        client_id=device.client_id,
        user_id=actor_user_id,
        action="SLOT_RESTOCKED",
        entity_type="MACHINE_SLOT",
        entity_id=slot.id,
        old_state={"slot": slot.slot_code, "stock": old_stock},
        new_state={"slot": slot.slot_code, "stock": slot.current_stock, "capacity": slot.capacity},
    ))

    db.commit()
    db.refresh(slot)
    return slot
