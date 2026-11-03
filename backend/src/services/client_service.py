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
    admin_username: Optional[str] = None,
    admin_password: Optional[str] = None,
    assign_device_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> Client:
    """Create a new client tenant organization, with optional initial vendor login and machine assignment."""
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

    # Create Vendor Admin User if password or username provided
    if admin_password or admin_username:
        from src.core.security.hashing import hash_password
        username = (admin_username or client_code.lower()).strip()
        pwd = admin_password or "Vendor@12345"

        existing_user = db.query(User).filter(
            (User.username == username) | (User.email == contact_email)
        ).first()
        if existing_user:
            existing_user.client_id = client.id
            existing_user.password_hash = hash_password(pwd)
            existing_user.role = "CLIENT_ADMIN"
            existing_user.status = "ACTIVE"
        else:
            vendor_user = User(
                client_id=client.id,
                username=username,
                email=contact_email,
                password_hash=hash_password(pwd),
                full_name=f"{name} Admin",
                role="CLIENT_ADMIN",
                status="ACTIVE",
            )
            db.add(vendor_user)

    # Assign initial device to this vendor if requested
    if assign_device_id:
        from src.db.models.device import Device
        device = db.query(Device).filter(
            (Device.device_id == assign_device_id.strip()) | (Device.id == assign_device_id.strip())
        ).first()
        if device:
            device.client_id = client.id
            device.status = "ASSIGNED"

    db.add(AuditLog(
        client_id=client.id,
        user_id=actor_user.id,
        action="CLIENT_CREATED",
        entity_type="CLIENT",
        entity_id=client.id,
        new_state={
            "client_code": client.client_code,
            "name": client.name,
            "vendor_username": admin_username,
            "assigned_device": assign_device_id,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    ))

    db.commit()
    db.refresh(client)
    return client


def create_client_user(
    db: Session,
    client_id: str,
    username: str,
    email: str,
    password: str,
    full_name: Optional[str] = None,
    actor_user: Optional[User] = None,
) -> User:
    """Create or reset credentials for a specific client tenant user."""
    client = get_client_by_id(db, client_id)
    from src.core.security.hashing import hash_password

    clean_username = username.strip()
    clean_email = email.strip()
    existing = db.query(User).filter(
        (User.username == clean_username) | (User.email == clean_email)
    ).first()

    if existing:
        existing.client_id = client.id
        existing.password_hash = hash_password(password)
        existing.role = "CLIENT_ADMIN"
        existing.status = "ACTIVE"
        if full_name:
            existing.full_name = full_name.strip()
        user = existing
    else:
        user = User(
            client_id=client.id,
            username=clean_username,
            email=clean_email,
            password_hash=hash_password(password),
            full_name=(full_name or f"{client.name} User").strip(),
            role="CLIENT_ADMIN",
            status="ACTIVE",
        )
        db.add(user)

    db.commit()
    db.refresh(user)
    return user


def list_clients(db: Session) -> List[Client]:
    """Retrieve all client organizations."""
    return db.query(Client).order_by(Client.created_at.desc()).all()


def get_client_by_id(db: Session, client_id: str) -> Client:
    """Retrieve client organization by primary key."""
    client = db.query(Client).filter_by(id=client_id).first()
    if not client:
        raise NotFoundException("Client", client_id)
    return client
