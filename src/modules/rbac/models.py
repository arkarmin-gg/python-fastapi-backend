from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="roles")
    permission_links: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )
    user_links = relationship("UserRole", back_populates="role")

    @property
    def permissions(self) -> list[Permission]:
        return [link.permission for link in self.permission_links]

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="roles_tenant_id_code_key"),
        Index("roles_tenant_id_is_active_idx", "tenant_id", "is_active"),
    )


class Permission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    module: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    role_links: Mapped[list[RolePermission]] = relationship(back_populates="permission")

    __table_args__ = (
        Index("permissions_code_idx", "code"),
        Index("permissions_module_idx", "module"),
    )


class RolePermission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "role_permissions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[Role] = relationship(back_populates="permission_links")
    permission: Mapped[Permission] = relationship(back_populates="role_links", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "role_id",
            "permission_id",
            name="role_permissions_tenant_id_role_id_permission_id_key",
        ),
        Index("role_permissions_tenant_id_role_id_idx", "tenant_id", "role_id"),
        Index("role_permissions_tenant_id_permission_id_idx", "tenant_id", "permission_id"),
    )
