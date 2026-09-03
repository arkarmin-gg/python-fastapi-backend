from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import UserStatus
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[UserStatus] = str_enum_column(
        UserStatus,
        nullable=False,
        default=UserStatus.ACTIVE,
        server_default=UserStatus.ACTIVE.value,
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_logout_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tenant = relationship("Tenant", back_populates="users")
    role_links: Mapped[list[UserRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    @property
    def role_ids(self) -> list[uuid.UUID]:
        return [link.role_id for link in self.role_links]

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="users_tenant_id_email_key"),
        Index("users_tenant_id_phone_idx", "tenant_id", "phone"),
        Index("users_tenant_id_status_idx", "tenant_id", "status"),
    )


class UserRole(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "user_roles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="role_links")
    role = relationship("Role", back_populates="user_links")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "role_id", name="user_roles_tenant_id_user_id_role_id_key"
        ),
        Index("user_roles_tenant_id_user_id_idx", "tenant_id", "user_id"),
        Index("user_roles_tenant_id_role_id_idx", "tenant_id", "role_id"),
    )
