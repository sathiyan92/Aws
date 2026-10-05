"""
Client Tenant Management Service.
Handles organization onboarding, updates, and tenant fleet metrics.
"""
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import func
from src.db.models.client import Client
from src.db.models.device import Device
from src.db.models.user import User
from src.db.models.audit import AuditLog
from src.core.exceptions.errors import NotFoundException, BadRequestException


def create_client(
    db: Session,
    client_code: str,
    name: str,
    contact_email: str,
    contact_phone: Optional[str],
    address: Optional[str],
    actor_user: User,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Client:
    """Create a new client tenant organization."""
    if db.query(Client).filter_by(client_code=client_code).first():
        raise BadRequestException(f"Client code '{client_code}' already exists")

    client = Client(
        client_code=client_code,
        name=name,
        contact_email=contact_email,
        contact_phone=contact_phone,
        status="ACTIVE",
        address=address,
    )
    db.add(client)
    db.flush()

    db.add(AuditLog(
        client_id=client.id,
        user_id=actor_user.id,
        action="CLIENT_CREATED",
        entity_type="CLIENT",
        entity_id=client.id,
        new_state={"client_code": client.client_code, "name": client.name},
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.commit()
    db.refresh(client)
    return client


def list_clients(db: Session) -> List[Client]:
    """Retrieve all client organizations."""
    return db.query(Client).order_by(Client.created_at.desc()).all()


def get_client_by_id(db: Session, client_id: str) -> Client:
    """Retrieve client organization by primary key."""
    client = db.query(Client).filter_by(id=client_id).first()
    if not client:
        raise NotFoundException("Client", client_id)
    return client
