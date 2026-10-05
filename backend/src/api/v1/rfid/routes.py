"""
RFID Attendance Subsystem API endpoints.
Enforces module policy guards on RFID card caches and attendance event streams.
"""
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.device import Device
from src.db.models.rfid import RFIDCard, AttendanceEvent
from src.core.security.dependencies import require_device_module

router = APIRouter(prefix="/rfid", tags=["RFID Subsystem"])


class RFIDCardSummary(BaseModel):
    card_uid: str
    employee_name: Optional[str] = None
    employee_code: Optional[str] = None
    status: str

    model_config = {"from_attributes": True}


class AttendanceEventSummary(BaseModel):
    id: str
    event_uuid: str
    device_id: str
    card_uid_scanned: str
    employee_name: Optional[str] = None
    event_type: str
    timestamp: datetime
    is_offline_sync: bool

    model_config = {"from_attributes": True}


class CreateRFIDCardRequest(BaseModel):
    card_uid: str
    employee_name: str
    employee_code: Optional[str] = None
    department: Optional[str] = None


@router.post("/{device_id}/cards", response_model=RFIDCardSummary)
def register_device_rfid_card(
    payload: CreateRFIDCardRequest,
    device: Device = Depends(require_device_module("RFID_ACCESS")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: RFID_ACCESS] Enroll a new authorized RFID card for the tenant's terminal.
    Rejects with 403 MODULE_DISABLED_FOR_DEVICE if RFID_ACCESS is disabled on device.
    """
    from src.db.models.rfid import Employee, RFIDCard
    import uuid

    # Find or create employee
    emp_code = payload.employee_code or f"EMP-{uuid.uuid4().hex[:6].upper()}"
    employee = db.query(Employee).filter(
        Employee.client_id == device.client_id,
        Employee.employee_code == emp_code,
    ).first()

    if not employee:
        employee = Employee(
            client_id=device.client_id,
            employee_code=emp_code,
            full_name=payload.employee_name,
            department=payload.department,
            status="ACTIVE",
        )
        db.add(employee)
        db.flush()

    card = db.query(RFIDCard).filter(
        RFIDCard.client_id == device.client_id,
        RFIDCard.card_uid == payload.card_uid,
    ).first()

    if not card:
        card = RFIDCard(
            client_id=device.client_id,
            employee_id=employee.id,
            card_uid=payload.card_uid,
            status="ACTIVE",
        )
        db.add(card)
    else:
        card.status = "ACTIVE"
        card.employee_id = employee.id

    # Bump config version for device sync
    device.current_config_version += 1
    if device.config:
        device.config.active_version = device.current_config_version
        device.config.is_synced = False

    db.commit()
    db.refresh(card)

    return RFIDCardSummary(
        card_uid=card.card_uid,
        employee_name=employee.full_name,
        employee_code=employee.employee_code,
        status=card.status,
    )


@router.get("/{device_id}/cards", response_model=List[RFIDCardSummary])
def get_device_rfid_cards(
    device: Device = Depends(require_device_module("RFID_ACCESS")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: RFID_ACCESS] Retrieve authorized RFID card whitelist cached for terminal.
    Rejects with 403 MODULE_DISABLED_FOR_DEVICE if RFID_ACCESS is disabled.
    """
    cards = db.query(RFIDCard).filter(RFIDCard.client_id == device.client_id).all()
    return [
        RFIDCardSummary(
            card_uid=c.card_uid,
            employee_name=c.employee.full_name if c.employee else None,
            employee_code=c.employee.employee_code if c.employee else None,
            status=c.status,
        )
        for c in cards
    ]


@router.get("/{device_id}/attendance", response_model=List[AttendanceEventSummary])
def get_device_attendance_events(
    device: Device = Depends(require_device_module("RFID_ACCESS")),
    db: Session = Depends(get_db),
):
    """
    [Guarded: RFID_ACCESS] Retrieve scanned attendance records for terminal.
    """
    events = db.query(AttendanceEvent).filter(
        AttendanceEvent.device_id == device.id,
    ).order_by(AttendanceEvent.timestamp.desc()).limit(50).all()

    return [
        AttendanceEventSummary(
            id=e.id,
            event_uuid=e.event_uuid,
            device_id=device.device_id,
            card_uid_scanned=e.card_uid_scanned,
            employee_name=e.employee.full_name if e.employee else "Unknown Tag",
            event_type=e.event_type,
            timestamp=e.timestamp,
            is_offline_sync=e.is_offline_sync,
        )
        for e in events
    ]
