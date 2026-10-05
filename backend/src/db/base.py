"""
Database base classes, common mixins, and UUID utilities for SQLAlchemy 2.0.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import DateTime, String, ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


def generate_uuid() -> str:
    """Generate a standard string UUIDv4."""
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    """Declarative base class for all SQLAlchemy ORM models."""
    pass


class TimestampMixin:
    """Mixin adding created_at and updated_at timezone-aware timestamps."""
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )


class TenantMixin:
    """Mixin enforcing multi-tenant isolation via mandatory client_id foreign key."""
    client_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
