"""
Client Tenant Management API endpoints.
Provides client onboarding, listing, and organization profile inspection.
"""
from typing import List
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.models.client import Client
from src.db.models.device import Device
from src.core.security.dependencies import (
    TenantContext,
    get_tenant_context,
    require_roles,
)
from src.services import client_service
from src.api.v1.clients.schemas import (
    ClientCreateRequest,
    ClientUpdateRequest,
    ClientResponse,
    ClientListResponse,
)

router = APIRouter(prefix="/clients", tags=["Client Tenant Management"])


def serialize_client(client: Client, db: Session) -> ClientResponse:
    """Format SQLAlchemy Client model into Pydantic ClientResponse with device counts."""
    total_devices = db.query(Device).filter(Device.client_id == client.id).count()
    active_devices = db.query(Device).filter(
        Device.client_id == client.id,
        Device.status == "ACTIVE",
    ).count()

    return ClientResponse(
        id=client.id,
        client_code=client.client_code,
        name=client.name,
        contact_email=client.contact_email,
        contact_phone=client.contact_phone,
        status=client.status,
        address=client.address,
        created_at=client.created_at,
        device_count=total_devices,
        active_device_count=active_devices,
    )


@router.post("", response_model=ClientResponse)
def create_client(
    payload: ClientCreateRequest,
    request: Request,
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] Onboard a new client tenant company.
    """
    client = client_service.create_client(
        db=db,
        client_code=payload.client_code,
        name=payload.name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        address=payload.address,
        actor_user=context.user,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    return serialize_client(client, db)


@router.get("", response_model=ClientListResponse)
def list_clients(
    context: TenantContext = Depends(require_roles("MANUFACTURER_ADMIN", "MANUFACTURER_SUPPORT")),
    db: Session = Depends(get_db),
):
    """
    [Manufacturer Only] List all onboarded client companies across the platform.
    """
    clients = client_service.list_clients(db)
    return ClientListResponse(
        total=len(clients),
        clients=[serialize_client(c, db) for c in clients],
    )


@router.get("/me", response_model=ClientResponse)
def get_current_client_profile(
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Retrieve organization profile for the requesting tenant.
    """
    if not context.client_id:
        return ClientResponse(
            id="manufacturer-root",
            client_code="MANUFACTURER",
            name="Platform Manufacturer Root",
            contact_email="admin@manufacturer.local",
            status="ACTIVE",
            created_at=context.user.created_at,
            device_count=db.query(Device).count(),
            active_device_count=db.query(Device).filter(Device.status == "ACTIVE").count(),
        )

    client = client_service.get_client_by_id(db, context.client_id)
    return serialize_client(client, db)


@router.get("/{client_id}", response_model=ClientResponse)
def get_client_by_id(
    client_id: str,
    context: TenantContext = Depends(get_tenant_context),
    db: Session = Depends(get_db),
):
    """
    Retrieve client details. Enforces tenant boundary:
    Manufacturer can view any client. Client can only view their own organization.
    """
    context.assert_tenant_access(client_id)
    client = client_service.get_client_by_id(db, client_id)
    return serialize_client(client, db)
