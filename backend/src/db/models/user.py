"""
User entity model supporting both Manufacturer Super-Admins and Client Tenant users.
"""
from typing import Optional, TYPE_CHECKING
from sqlalchemy import String, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.db.base import Base, TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from src.db.models.client import Client


class User(Base, TimestampMixin):
    """
    User account entity with role-based access control (RBAC).
    Manufacturer staff have client_id=NULL. Client users have a mandatory client_id.
    """
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    client_id: Mapped[Optional[str]] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(32),
        index=True,
        nullable=False,
    )  # MANUFACTURER_ADMIN, MANUFACTURER_SUPPORT, CLIENT_ADMIN, CLIENT_OPERATOR, CLIENT_VIEWER
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", index=True, nullable=False)  # ACTIVE, SUSPENDED, INACTIVE

    # Relationship
    client: Mapped[Optional["Client"]] = relationship("Client", back_populates="users")

    __table_args__ = (
        Index("idx_users_client_role", "client_id", "role"),
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username='{self.username}', role='{self.role}', client_id='{self.client_id}')>"
