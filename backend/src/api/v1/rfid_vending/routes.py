"""
RFID Vending Machine Management & Telemetry API Router.
Supports:
- 1,000 users/cards per machine scale
- Method A: Excel/CSV bulk import
- Method B: Batch sequential card generator
- Method C: Live bench tap-to-enroll mode
- Hardware tap verification & offline cache sync for ESP32
- Calendar, vendor, and machine-filtered Excel/CSV reporting
"""
import io
import csv
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, date, time
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, desc

from src.db.session import get_db
from src.db.base import utc_now, generate_uuid
from src.db.models.client import Client
from src.db.models.device import Device
from src.db.models.rfid_vending import RFIDVendingCard, RFIDVendingLog
from src.core.security.dependencies import TenantContext, get_tenant_context, get_current_user
from src.api.v1.rfid_vending.schemas import (
    RFIDCardCreate,
    RFIDCardUpdate,
    RFIDCardResponse,
    RFIDCardBatchGenerate,
    RFIDVerifyTapRequest,
    RFIDVerifyTapResponse,
    RFIDOfflineSyncRequest,
    RFIDLogItem,
    EnrollModeToggle,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/rfid-vending", tags=["RFID Vending Subsystem"])

# In-memory storage for active Method C Live Tap Enroll sessions
# device_id -> { "active": bool, "last_uid": str, "timestamp": datetime }
_ENROLL_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _clean_uid(raw_uid: str) -> str:
    """Normalize RFID UID: uppercase hex, strip colons, spaces, and hyphens."""
    if not raw_uid or hasattr(raw_uid, "default"):
        return ""
    cleaned = str(raw_uid).strip().upper().replace(":", "").replace("-", "").replace(" ", "")
    return cleaned


def _param(val, default=None):
    """Safely extract parameter value whether invoked via FastAPI injection or directly."""
    if hasattr(val, "default"):
        return val.default
    return val if val is not None else default


# ==============================================================================
# 1. CARD CRUD & MANAGEMENT (1,000 Cards Scale)
# ==============================================================================

@router.get("/cards")
def list_rfid_cards(
    device_id: Optional[str] = Query(None, description="Filter by device ID or machine code"),
    client_id: Optional[str] = Query(None, description="Filter by vendor / client ID"),
    search: Optional[str] = Query(None, description="Search by username, department, or card UID"),
    is_active: Optional[bool] = Query(None, description="Filter by active status"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    List authorized RFID cards with search, filtering, and high-scale pagination.
    Tenants are restricted to their own organization's cards.
    """
    device_id = _param(device_id)
    client_id = _param(client_id)
    search = _param(search)
    is_active = _param(is_active)
    limit = int(_param(limit, 1000))
    offset = int(_param(offset, 0))

    query = db.query(RFIDVendingCard)

    # Multi-tenant scoping
    if context.role != "MANUFACTURER_ADMIN":
        query = query.filter(RFIDVendingCard.client_id == context.client_id)
    elif client_id and isinstance(client_id, str):
        query = query.filter(RFIDVendingCard.client_id == client_id)

    # Device filter
    if device_id and isinstance(device_id, str):
        dev = db.query(Device).filter(
            (Device.id == device_id) | (Device.device_id == device_id)
        ).first()
        if dev:
            query = query.filter(or_(RFIDVendingCard.device_id == dev.id, RFIDVendingCard.device_id == None))
        else:
            query = query.filter(RFIDVendingCard.device_id == device_id)

    # Active status filter
    if is_active is not None and isinstance(is_active, bool):
        query = query.filter(RFIDVendingCard.is_active == is_active)

    # Search filter
    if search and isinstance(search, str):
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                RFIDVendingCard.card_uid.ilike(s),
                RFIDVendingCard.username.ilike(s),
                RFIDVendingCard.department.ilike(s),
            )
        )

    total_count = query.count()
    cards = query.order_by(RFIDVendingCard.created_at.desc()).offset(offset).limit(limit).all()

    # Enrich with device code
    results = []
    for c in cards:
        dev_code = c.device.device_id if c.device else "All Tenant Machines"
        results.append({
            "id": c.id,
            "client_id": c.client_id,
            "device_id": c.device_id,
            "device_code": dev_code,
            "card_uid": c.card_uid,
            "username": c.username,
            "department": c.department,
            "daily_limit": c.daily_limit,
            "used_today": c.used_today,
            "last_vended_at": c.last_vended_at,
            "is_active": c.is_active,
            "notes": c.notes,
            "created_at": c.created_at,
            "updated_at": c.updated_at,
        })

    return {
        "total": total_count,
        "count": len(results),
        "cards": results,
    }


@router.post("/cards")
def create_rfid_card(
    payload: RFIDCardCreate,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    Enroll or update a single RFID card.
    """
    target_client_id = context.client_id
    clean_uid = _clean_uid(payload.card_uid)
    if not clean_uid:
        raise HTTPException(status_code=400, detail="Card UID cannot be empty.")

    target_device_id = None
    if payload.device_id:
        dev = db.query(Device).filter(
            (Device.id == payload.device_id) | (Device.device_id == payload.device_id)
        ).first()
        if dev:
            target_device_id = dev.id
            if context.role == "MANUFACTURER_ADMIN" and not target_client_id:
                target_client_id = dev.client_id

    if not target_client_id:
        client = db.query(Client).first()
        target_client_id = client.id if client else None

    # Check existing
    existing = db.query(RFIDVendingCard).filter(
        RFIDVendingCard.client_id == target_client_id,
        RFIDVendingCard.card_uid == clean_uid,
    ).first()

    if existing:
        existing.username = payload.username
        existing.department = payload.department
        existing.daily_limit = payload.daily_limit
        existing.is_active = payload.is_active
        existing.notes = payload.notes
        if target_device_id is not None:
            existing.device_id = target_device_id
        db.commit()
        db.refresh(existing)
        return {"message": "Card updated successfully", "card_id": existing.id, "card_uid": existing.card_uid}

    new_card = RFIDVendingCard(
        client_id=target_client_id,
        device_id=target_device_id,
        card_uid=clean_uid,
        username=payload.username,
        department=payload.department,
        daily_limit=payload.daily_limit,
        is_active=payload.is_active,
        notes=payload.notes,
    )
    db.add(new_card)
    db.commit()
    db.refresh(new_card)
    return {"message": "Card enrolled successfully", "card_id": new_card.id, "card_uid": new_card.card_uid}


@router.put("/cards/{card_id}")
def update_rfid_card(
    card_id: str,
    payload: RFIDCardUpdate,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    Update existing card details (username, limit, active toggle, notes).
    """
    card = db.query(RFIDVendingCard).filter(RFIDVendingCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found.")

    if context.role != "MANUFACTURER_ADMIN" and card.client_id != context.client_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    if payload.username is not None:
        card.username = payload.username
    if payload.department is not None:
        card.department = payload.department
    if payload.daily_limit is not None:
        card.daily_limit = payload.daily_limit
    if payload.is_active is not None:
        card.is_active = payload.is_active
    if payload.notes is not None:
        card.notes = payload.notes
    if payload.device_id is not None:
        if payload.device_id == "":
            card.device_id = None
        else:
            dev = db.query(Device).filter(
                (Device.id == payload.device_id) | (Device.device_id == payload.device_id)
            ).first()
            card.device_id = dev.id if dev else payload.device_id

    db.commit()
    db.refresh(card)
    return {"message": "Card updated", "card_id": card.id}


@router.delete("/cards/{card_id}")
def delete_rfid_card(
    card_id: str,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    Remove an RFID card from the authorized list.
    """
    card = db.query(RFIDVendingCard).filter(RFIDVendingCard.id == card_id).first()
    if not card:
        raise HTTPException(status_code=404, detail="Card not found.")

    if context.role != "MANUFACTURER_ADMIN" and card.client_id != context.client_id:
        raise HTTPException(status_code=403, detail="Access denied.")

    db.delete(card)
    db.commit()
    return {"message": "Card removed successfully", "card_id": card_id}


# ==============================================================================
# 2. METHOD A: EXCEL & CSV BULK TEMPLATE & IMPORT
# ==============================================================================

@router.get("/template")
def download_card_template():
    """
    Download pre-formatted CSV template for 1,000-card bulk upload.
    """
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["card_uid", "username", "department", "daily_limit", "is_active", "notes"])
    writer.writerow(["A1B2C3D4", "Rajesh Kumar", "Operations", "2", "TRUE", "Morning Shift"])
    writer.writerow(["E5F6G7H8", "Priya Sharma", "Engineering", "1", "TRUE", "R&D Lab"])
    writer.writerow(["99AABBCC", "Amit Patel", "Warehouse", "3", "TRUE", "Logistics Team"])

    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=rfid_cards_upload_template.csv"},
    )


@router.post("/bulk-upload")
async def bulk_upload_rfid_cards(
    file: UploadFile = File(...),
    device_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    [Method A] Bulk upload up to 1,000+ RFID cards via CSV or Excel (.xlsx).
    Handles instant batch upserts in a single fast transaction.
    """
    target_client_id = context.client_id
    if context.role == "MANUFACTURER_ADMIN" and client_id:
        target_client_id = client_id

    target_device_id = None
    if device_id:
        dev = db.query(Device).filter(
            (Device.id == device_id) | (Device.device_id == device_id)
        ).first()
        if dev:
            target_device_id = dev.id
            if not target_client_id:
                target_client_id = dev.client_id

    if not target_client_id:
        client = db.query(Client).first()
        target_client_id = client.id if client else None

    content = await file.read()
    filename = file.filename.lower() if file.filename else "upload.csv"

    rows = []
    if filename.endswith(".xlsx") or filename.endswith(".xls"):
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
            sheet = wb.active
            headers = [str(cell.value or "").strip().lower() for cell in next(sheet.iter_rows())]
            for row_cells in sheet.iter_rows(min_row=2, values_only=True):
                if not any(row_cells):
                    continue
                row_dict = {}
                for idx, val in enumerate(row_cells):
                    if idx < len(headers):
                        row_dict[headers[idx]] = str(val or "").strip()
                rows.append(row_dict)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse Excel file: {str(e)}")
    else:
        # Standard CSV parser
        try:
            text_stream = io.StringIO(content.decode("utf-8-sig", errors="ignore"))
            reader = csv.DictReader(text_stream)
            for row in reader:
                cleaned_row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
                rows.append(cleaned_row)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to parse CSV file: {str(e)}")

    if not rows:
        raise HTTPException(status_code=400, detail="The uploaded file contains no data rows.")

    # Batch process rows
    imported_count = 0
    updated_count = 0
    skipped_count = 0
    errors = []

    # Preload existing cards for this tenant to optimize batch lookups
    existing_cards = {
        c.card_uid: c
        for c in db.query(RFIDVendingCard).filter(RFIDVendingCard.client_id == target_client_id).all()
    }

    for idx, r in enumerate(rows, start=2):
        uid = _clean_uid(r.get("card_uid") or r.get("uid") or r.get("card_number") or r.get("card") or "")
        username = r.get("username") or r.get("name") or r.get("cardholder") or f"Cardholder-{uid}"
        dept = r.get("department") or r.get("dept") or None
        notes = r.get("notes") or None

        limit_raw = r.get("daily_limit") or r.get("limit") or "1"
        try:
            daily_limit = int(limit_raw)
        except ValueError:
            daily_limit = 1

        active_raw = str(r.get("is_active") or r.get("active") or "true").lower()
        is_active = active_raw in ("true", "1", "yes", "y", "active")

        if not uid:
            skipped_count += 1
            errors.append(f"Row {idx}: missing card UID")
            continue

        if uid in existing_cards:
            card = existing_cards[uid]
            card.username = username
            card.department = dept
            card.daily_limit = daily_limit
            card.is_active = is_active
            if target_device_id:
                card.device_id = target_device_id
            if notes:
                card.notes = notes
            updated_count += 1
        else:
            new_card = RFIDVendingCard(
                client_id=target_client_id,
                device_id=target_device_id,
                card_uid=uid,
                username=username,
                department=dept,
                daily_limit=daily_limit,
                is_active=is_active,
                notes=notes,
            )
            db.add(new_card)
            existing_cards[uid] = new_card
            imported_count += 1

    db.commit()

    return {
        "success": True,
        "total_rows": len(rows),
        "imported": imported_count,
        "updated": updated_count,
        "skipped": skipped_count,
        "errors": errors[:10],
    }


# ==============================================================================
# 3. METHOD B: BATCH SEQUENTIAL CARD NUMBER GENERATOR
# ==============================================================================

@router.post("/batch-generate")
def batch_generate_cards(
    payload: RFIDCardBatchGenerate,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    [Method B] Instantly generate a sequential range of up to 1,000 cards.
    E.g., Start=1, End=1000 creates USER-0001 through USER-1000 with unique card UIDs.
    """
    target_client_id = context.client_id
    if context.role == "MANUFACTURER_ADMIN" and payload.client_id:
        target_client_id = payload.client_id

    target_device_id = None
    if payload.device_id:
        dev = db.query(Device).filter(
            (Device.id == payload.device_id) | (Device.device_id == payload.device_id)
        ).first()
        if dev:
            target_device_id = dev.id
            if not target_client_id:
                target_client_id = dev.client_id

    if not target_client_id:
        client = db.query(Client).first()
        target_client_id = client.id if client else None

    count = payload.end_num - payload.start_num + 1
    if count <= 0 or count > 5000:
        raise HTTPException(status_code=400, detail="Invalid range. Must generate between 1 and 5000 cards.")

    existing_uids = {
        c.card_uid
        for c in db.query(RFIDVendingCard.card_uid).filter(RFIDVendingCard.client_id == target_client_id).all()
    }

    created = 0
    skipped = 0
    prefix_uid = (payload.uid_prefix or "RFC-").upper()

    for i in range(payload.start_num, payload.end_num + 1):
        num_str = str(i).zfill(payload.pad_digits)
        uid = f"{prefix_uid}{num_str}"
        username = f"{payload.prefix}{num_str}"

        if uid in existing_uids:
            skipped += 1
            continue

        card = RFIDVendingCard(
            client_id=target_client_id,
            device_id=target_device_id,
            card_uid=uid,
            username=username,
            department=payload.department,
            daily_limit=payload.daily_limit,
            is_active=True,
        )
        db.add(card)
        existing_uids.add(uid)
        created += 1

    db.commit()
    return {
        "success": True,
        "requested": count,
        "created": created,
        "skipped_existing": skipped,
    }


# ==============================================================================
# 4. METHOD C: LIVE BENCH TAP-TO-ENROLL MODE
# ==============================================================================

@router.post("/devices/{device_id}/enroll-mode")
def toggle_enroll_mode(
    device_id: str,
    payload: EnrollModeToggle,
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    [Method C] Turn Live Tap Enrollment Mode ON or OFF for a specific machine.
    When ON, any card tapped at the machine sends its UID straight to the portal UI.
    """
    dev = db.query(Device).filter(
        (Device.id == device_id) | (Device.device_id == device_id)
    ).first()
    if not dev:
        raise HTTPException(status_code=404, detail="Device not found.")

    key = dev.device_id
    if payload.enabled:
        _ENROLL_SESSIONS[key] = {
            "active": True,
            "last_uid": None,
            "timestamp": None,
            "started_at": utc_now(),
        }
    else:
        _ENROLL_SESSIONS.pop(key, None)

    return {
        "device_id": key,
        "enroll_mode": payload.enabled,
        "message": f"Enrollment mode {'ACTIVATED' if payload.enabled else 'DEACTIVATED'} for {key}",
    }


@router.get("/devices/{device_id}/enroll-status")
def get_enroll_status(
    device_id: str,
    db: Session = Depends(get_db),
):
    """
    [Method C] Web portal polls this while in enrollment mode to check if a new card was tapped.
    """
    dev = db.query(Device).filter(
        (Device.id == device_id) | (Device.device_id == device_id)
    ).first()
    key = dev.device_id if dev else device_id

    session_data = _ENROLL_SESSIONS.get(key)
    if not session_data or not session_data.get("active"):
        return {"enroll_active": False, "last_uid": None}

    last_uid = session_data.get("last_uid")
    # Consume UID once read so UI only triggers once per tap
    session_data["last_uid"] = None

    return {
        "enroll_active": True,
        "last_uid": last_uid,
        "timestamp": session_data.get("timestamp"),
    }


# ==============================================================================
# 5. HARDWARE ENDPOINTS: TAP VERIFICATION & FULL 1,000-CARD SYNC FOR ESP32
# ==============================================================================

@router.post("/verify-tap", response_model=RFIDVerifyTapResponse)
def verify_device_tap(
    payload: RFIDVerifyTapRequest,
    db: Session = Depends(get_db),
):
    """
    [Hardware Endpoint: ESP32 MFRC522]
    Called by ESP32 when an RFID card is tapped at the vending machine.
    1. Checks if machine is in Method C Enroll Mode -> captures UID.
    2. Verifies card authorization and status in database.
    3. Checks daily vend quota.
    4. Records event to RFIDVendingLog.
    5. Returns dispense pulse authorization.
    """
    clean_uid = _clean_uid(payload.card_uid)
    dev = db.query(Device).filter(
        (Device.id == payload.device_id) | (Device.device_id == payload.device_id) | (Device.mac_address.ilike(payload.device_id.strip()))
    ).first()

    if not dev:
        return RFIDVerifyTapResponse(
            authorized=False,
            status="UNKNOWN_DEVICE",
            card_uid=clean_uid,
            message="Machine not recognized in fleet.",
        )

    dev_key = dev.device_id

    # Check Method C Live Enroll Mode
    enroll_sess = _ENROLL_SESSIONS.get(dev_key)
    if enroll_sess and enroll_sess.get("active"):
        enroll_sess["last_uid"] = clean_uid
        enroll_sess["timestamp"] = utc_now().isoformat()
        logger.info(f"[Enroll Mode] Captured card {clean_uid} on device {dev_key}")

    # Look up card in database for this client or machine
    card = db.query(RFIDVendingCard).filter(
        RFIDVendingCard.client_id == dev.client_id,
        RFIDVendingCard.card_uid == clean_uid,
        or_(RFIDVendingCard.device_id == dev.id, RFIDVendingCard.device_id == None),
    ).first()

    # 1. Unregistered Card
    if not card:
        log_entry = RFIDVendingLog(
            client_id=dev.client_id,
            device_id=dev.id,
            card_uid=clean_uid,
            username="Unknown Cardholder",
            status="UNKNOWN_CARD",
            pulse_duration_ms=0,
            notes="Tapped card UID not found in whitelist",
        )
        db.add(log_entry)
        db.commit()

        msg = "Captured in Enroll Mode" if (enroll_sess and enroll_sess.get("active")) else "Card Not Registered"
        return RFIDVerifyTapResponse(
            authorized=False,
            status="UNKNOWN_CARD",
            card_uid=clean_uid,
            message=msg,
        )

    # 2. Inactive / Blocked Card
    if not card.is_active:
        log_entry = RFIDVendingLog(
            client_id=dev.client_id,
            device_id=dev.id,
            card_uid=clean_uid,
            username=card.username,
            department=card.department,
            status="BLOCKED_CARD",
            pulse_duration_ms=0,
            notes="Card is blocked or inactive",
        )
        db.add(log_entry)
        db.commit()

        return RFIDVerifyTapResponse(
            authorized=False,
            status="BLOCKED_CARD",
            card_uid=clean_uid,
            username=card.username,
            department=card.department,
            message="Card Access Suspended",
        )

    # 3. Daily Limit Verification
    now = utc_now()
    today_date = now.date()

    # Reset daily counter if last vend was on a previous calendar day
    if card.last_vended_at is None or card.last_vended_at.date() != today_date:
        card.used_today = 0

    if card.daily_limit > 0 and card.used_today >= card.daily_limit:
        log_entry = RFIDVendingLog(
            client_id=dev.client_id,
            device_id=dev.id,
            card_uid=clean_uid,
            username=card.username,
            department=card.department,
            status="DAILY_LIMIT_EXCEEDED",
            pulse_duration_ms=0,
            notes=f"Limit {card.daily_limit} reached ({card.used_today} used)",
        )
        db.add(log_entry)
        db.commit()

        return RFIDVerifyTapResponse(
            authorized=False,
            status="DAILY_LIMIT_EXCEEDED",
            card_uid=clean_uid,
            username=card.username,
            department=card.department,
            daily_limit=card.daily_limit,
            used_today=card.used_today,
            message="Daily Dispense Quota Reached",
        )

    # 4. Authorized Dispense!
    card.used_today += 1
    card.last_vended_at = now

    pulse_ms = payload.pulse_ms or 1500

    log_entry = RFIDVendingLog(
        client_id=dev.client_id,
        device_id=dev.id,
        card_uid=clean_uid,
        username=card.username,
        department=card.department,
        status="DISPENSED_SUCCESS",
        pulse_duration_ms=pulse_ms,
        notes=f"Successful dispense ({card.used_today}/{card.daily_limit})",
    )
    db.add(log_entry)
    db.commit()

    return RFIDVerifyTapResponse(
        authorized=True,
        status="DISPENSED_SUCCESS",
        card_uid=clean_uid,
        username=card.username,
        department=card.department,
        daily_limit=card.daily_limit,
        used_today=card.used_today,
        dispense_pulse_ms=pulse_ms,
        message=f"Welcome {card.username}! Dispensing...",
    )


@router.get("/devices/{device_id}/sync-cards")
def sync_cards_to_device(
    device_id: str,
    db: Session = Depends(get_db),
):
    """
    [Hardware Sync Endpoint: ESP32 Boot / Refresh]
    Returns all active authorized cards for the machine.
    Used by ESP32 to populate its local 1,000-card RAM cache for instant offline vending.
    """
    dev = db.query(Device).filter(
        (Device.id == device_id) | (Device.device_id == device_id) | (Device.mac_address.ilike(device_id.strip()))
    ).first()

    if not dev:
        raise HTTPException(status_code=404, detail="Device not found.")

    cards = db.query(RFIDVendingCard).filter(
        RFIDVendingCard.client_id == dev.client_id,
        RFIDVendingCard.is_active == True,
        or_(RFIDVendingCard.device_id == dev.id, RFIDVendingCard.device_id == None),
    ).all()

    today_date = utc_now().date()
    card_list = []
    for c in cards:
        used = c.used_today if (c.last_vended_at and c.last_vended_at.date() == today_date) else 0
        card_list.append({
            "uid": c.card_uid,
            "name": c.username,
            "limit": c.daily_limit,
            "used": used,
        })

    return {
        "device_id": dev.device_id,
        "count": len(card_list),
        "timestamp": utc_now().isoformat(),
        "cards": card_list,
    }


@router.post("/offline-sync")
def upload_offline_vending_logs(
    payload: RFIDOfflineSyncRequest,
    db: Session = Depends(get_db),
):
    """
    Upload offline vends buffered in ESP32 Flash when network was down.
    """
    dev = db.query(Device).filter(
        (Device.id == payload.device_id) | (Device.device_id == payload.device_id) | (Device.mac_address.ilike(payload.device_id.strip()))
    ).first()

    if not dev:
        raise HTTPException(status_code=404, detail="Device not found.")

    inserted = 0
    for item in payload.logs:
        clean_uid = _clean_uid(item.card_uid)
        card = db.query(RFIDVendingCard).filter(
            RFIDVendingCard.client_id == dev.client_id,
            RFIDVendingCard.card_uid == clean_uid,
        ).first()

        username = card.username if card else "Offline User"
        dept = card.department if card else None

        log_entry = RFIDVendingLog(
            client_id=dev.client_id,
            device_id=dev.id,
            card_uid=clean_uid,
            username=username,
            department=dept,
            status="OFFLINE_SYNCED_DISPENSE",
            pulse_duration_ms=item.dispense_ms or 1500,
            timestamp=item.timestamp or utc_now(),
            notes="Logged while offline; synced upon network reconnection.",
        )
        db.add(log_entry)
        inserted += 1

    db.commit()
    return {"success": True, "synced_count": inserted}


# ==============================================================================
# 6. CALENDAR & VENDOR & MACHINE FILTERED REPORTS & EXCEL EXPORT
# ==============================================================================

@router.get("/reports")
def get_vending_reports(
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    client_id: Optional[str] = Query(None, description="Vendor / Client ID"),
    device_id: Optional[str] = Query(None, description="Machine ID or code"),
    status: Optional[str] = Query(None, description="Filter by status (DISPENSED_SUCCESS, etc.)"),
    search: Optional[str] = Query(None, description="Search username or UID"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    Fetch filtered RFID vending audit records for web table display.
    """
    start_date = _param(start_date)
    end_date = _param(end_date)
    client_id = _param(client_id)
    device_id = _param(device_id)
    status = _param(status)
    search = _param(search)
    limit = int(_param(limit, 100))
    offset = int(_param(offset, 0))

    query = db.query(RFIDVendingLog)

    # Tenant isolation
    if context.role != "MANUFACTURER_ADMIN":
        query = query.filter(RFIDVendingLog.client_id == context.client_id)
    elif client_id and isinstance(client_id, str):
        query = query.filter(RFIDVendingLog.client_id == client_id)

    # Machine filter
    if device_id and isinstance(device_id, str):
        dev = db.query(Device).filter(
            (Device.id == device_id) | (Device.device_id == device_id)
        ).first()
        if dev:
            query = query.filter(RFIDVendingLog.device_id == dev.id)
        else:
            query = query.filter(RFIDVendingLog.device_id == device_id)

    # Calendar date range filter
    if start_date and isinstance(start_date, str):
        try:
            s_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(RFIDVendingLog.timestamp >= s_dt)
        except ValueError:
            pass

    if end_date and isinstance(end_date, str):
        try:
            e_dt = datetime.combine(datetime.strptime(end_date, "%Y-%m-%d").date(), time.max)
            query = query.filter(RFIDVendingLog.timestamp <= e_dt)
        except ValueError:
            pass

    # Status filter
    if status and isinstance(status, str):
        query = query.filter(RFIDVendingLog.status == status)

    # Search filter
    if search and isinstance(search, str):
        s = f"%{search.strip()}%"
        query = query.filter(
            or_(
                RFIDVendingLog.card_uid.ilike(s),
                RFIDVendingLog.username.ilike(s),
                RFIDVendingLog.department.ilike(s),
            )
        )

    total_count = query.count()
    logs = query.order_by(desc(RFIDVendingLog.timestamp)).offset(offset).limit(limit).all()

    items = []
    for l in logs:
        vendor_name = l.client.name if l.client else "Default Vendor"
        dev_code = l.device.device_id if l.device else "VM-000001"
        items.append({
            "id": l.id,
            "timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "client_id": l.client_id,
            "vendor_name": vendor_name,
            "device_id": l.device_id,
            "device_code": dev_code,
            "card_uid": l.card_uid,
            "username": l.username,
            "department": l.department,
            "status": l.status,
            "pulse_duration_ms": l.pulse_duration_ms,
            "notes": l.notes,
        })

    return {
        "total": total_count,
        "count": len(items),
        "logs": items,
    }


@router.get("/reports/export")
def export_vending_reports(
    start_date: Optional[str] = Query(None, description="Start date YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="End date YYYY-MM-DD"),
    client_id: Optional[str] = Query(None, description="Vendor / Client ID"),
    device_id: Optional[str] = Query(None, description="Machine ID or code"),
    status: Optional[str] = Query(None, description="Filter status"),
    format: str = Query("xlsx", description="xlsx or csv"),
    db: Session = Depends(get_db),
    context: TenantContext = Depends(get_tenant_context),
):
    """
    Export RFID Vending Reports filtered by:
    - Calendar Date Range (start_date to end_date)
    - Vendor Organization (client_id)
    - Vending Machine (device_id)
    - Status
    Generates a beautifully styled Excel workbook (.xlsx) or CSV file.
    """
    start_date = _param(start_date)
    end_date = _param(end_date)
    client_id = _param(client_id)
    device_id = _param(device_id)
    status = _param(status)
    format = str(_param(format, "xlsx"))

    query = db.query(RFIDVendingLog)

    # Tenant isolation
    if context.role != "MANUFACTURER_ADMIN":
        query = query.filter(RFIDVendingLog.client_id == context.client_id)
    elif client_id and isinstance(client_id, str):
        query = query.filter(RFIDVendingLog.client_id == client_id)

    # Machine filter
    machine_code = "All Machines"
    if device_id and isinstance(device_id, str):
        dev = db.query(Device).filter(
            (Device.id == device_id) | (Device.device_id == device_id)
        ).first()
        if dev:
            query = query.filter(RFIDVendingLog.device_id == dev.id)
            machine_code = dev.device_id
        else:
            query = query.filter(RFIDVendingLog.device_id == device_id)

    # Calendar range
    if start_date and isinstance(start_date, str):
        try:
            s_dt = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(RFIDVendingLog.timestamp >= s_dt)
        except ValueError:
            pass

    if end_date and isinstance(end_date, str):
        try:
            e_dt = datetime.combine(datetime.strptime(end_date, "%Y-%m-%d").date(), time.max)
            query = query.filter(RFIDVendingLog.timestamp <= e_dt)
        except ValueError:
            pass

    if status and isinstance(status, str):
        query = query.filter(RFIDVendingLog.status == status)

    logs = query.order_by(desc(RFIDVendingLog.timestamp)).limit(10000).all()

    filename_prefix = f"rfid_vending_report_{start_date or 'all'}_to_{end_date or 'today'}"

    # Export to Excel (.xlsx)
    if format.lower() == "xlsx":
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "RFID Vending Report"

        # Title Block
        ws.merge_cells("A1:H1")
        title_cell = ws["A1"]
        title_cell.value = "Smart IoT Vending Machine - RFID Card Usage Report"
        title_cell.font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
        title_cell.fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 36

        # Subtitle / Filter Summary
        ws.merge_cells("A2:H2")
        sub_cell = ws["A2"]
        date_str = f"Date Range: {start_date or 'Beginning'} to {end_date or 'Present'}"
        sub_cell.value = f"{date_str}  |  Machine: {machine_code}  |  Total Records: {len(logs)}"
        sub_cell.font = Font(name="Calibri", size=10, italic=True, color="64748B")
        sub_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[2].height = 20

        # Headers
        headers = [
            "Log ID",
            "Date & Time",
            "Vendor / Client",
            "Machine Code",
            "Card UID",
            "Cardholder Name",
            "Department / Role",
            "Dispense Status",
            "Motor Pulse (ms)",
            "Remarks",
        ]
        ws.append([])  # blank row 3
        ws.append(headers)  # row 4

        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
        thin_border = Border(
            left=Side(style='thin', color='E2E8F0'),
            right=Side(style='thin', color='E2E8F0'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1'),
        )

        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=4, column=col_idx)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[4].height = 26

        # Rows
        for r_idx, l in enumerate(logs, start=5):
            vendor_name = l.client.name if l.client else "Default Vendor"
            dev_code = l.device.device_id if l.device else "VM-000001"

            # Color code status
            status_text = l.status
            if status_text in ("DISPENSED_SUCCESS", "OFFLINE_SYNCED_DISPENSE"):
                status_color = "15803D"  # green
            elif status_text == "DAILY_LIMIT_EXCEEDED":
                status_color = "D97706"  # amber
            else:
                status_color = "DC2626"  # red

            row_data = [
                l.id[:8].upper(),
                l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                vendor_name,
                dev_code,
                l.card_uid,
                l.username,
                l.department or "-",
                status_text,
                l.pulse_duration_ms,
                l.notes or "",
            ]
            ws.append(row_data)

            # Styling
            row_fill = PatternFill(start_color="F8FAFC" if r_idx % 2 == 0 else "FFFFFF", fill_type="solid")
            for c_idx in range(1, len(row_data) + 1):
                c = ws.cell(row=r_idx, column=c_idx)
                c.fill = row_fill
                c.border = thin_border
                c.font = Font(name="Calibri", size=10)
                if c_idx in (1, 2, 4, 5, 9):
                    c.alignment = Alignment(horizontal="center")
                elif c_idx == 8:
                    c.alignment = Alignment(horizontal="center")
                    c.font = Font(name="Calibri", size=10, bold=True, color=status_color)

        # Auto-adjust column widths
        from openpyxl.utils import get_column_letter
        for col_idx, col in enumerate(ws.columns, start=1):
            max_len = 0
            col_letter = get_column_letter(col_idx)
            for cell in col:
                val = str(cell.value or "")
                if len(val) > max_len and cell.row > 2:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

        excel_stream = io.BytesIO()
        wb.save(excel_stream)
        excel_stream.seek(0)

        return StreamingResponse(
            excel_stream,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f"attachment; filename={filename_prefix}.xlsx"},
        )

    # Standard CSV fallback
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "log_id",
        "timestamp",
        "vendor_name",
        "machine_code",
        "card_uid",
        "username",
        "department",
        "status",
        "pulse_duration_ms",
        "notes",
    ])
    for l in logs:
        v_name = l.client.name if l.client else "Default Vendor"
        d_code = l.device.device_id if l.device else "VM-000001"
        writer.writerow([
            l.id,
            l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            v_name,
            d_code,
            l.card_uid,
            l.username,
            l.department or "",
            l.status,
            l.pulse_duration_ms,
            l.notes or "",
        ])

    output.seek(0)
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename_prefix}.csv"},
    )
