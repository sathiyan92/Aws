"""
Audit Log query schemas and API router.
Allows manufacturer super-admins to inspect immutable system and operational audit trails.
"""
from typing import List, Optional, Any
from datetime import datetime
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.audit import AuditLog
from src.core.security.dependencies import (
    TenantContext,
    require_roles,
)

router = APIRouter(prefix="/audit-logs", tags=["Audit Logs"])


class AuditLogResponse(BaseModel):
    """Audit log entry representation."""
    id: str
    client_id: Optional[str] = None
    user_id: Optional[str] = None
    action: str
    entity_type: str
    entity_id: str
    old_state: Optional[Any] = None
    new_state: Optional[Any] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogListResponse(BaseModel):
    total: int
    logs: List[AuditLogResponse]


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    action: Optional[str] = Query(None, description="Filter by action code"),
    entity_type: Optional[str] = Query(None, description="Filter by entity type (DEVICE, CLIENT, USER, etc.)"),
    client_id: Optional[str] = Query(None, description="Filter by client ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN", "MANUFACTURER_SUPPORT")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Query immutable audit trail logs.
    """
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if entity_type:
        query = query.filter(AuditLog.entity_type == entity_type)
    if client_id:
        query = query.filter(AuditLog.client_id == client_id)

    total = query.count()
    logs = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(limit).all()

    return AuditLogListResponse(
        total=total,
        logs=[AuditLogResponse.model_validate(log) for log in logs],
    )
