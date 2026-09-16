from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Permission(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    module: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    role_links: Mapped[list[RolePermission]] = relationship(back_populates="permission")
    template_links: Mapped[list[RoleTemplatePermission]] = relationship(back_populates="permission")

    __table_args__ = (
        Index("permissions_module_idx", "module"),
        Index("permissions_module_is_active_idx", "module", "is_active"),
    )


class RoleTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "role_templates"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    permission_links: Mapped[list[RoleTemplatePermission]] = relationship(
        back_populates="role_template", cascade="all, delete-orphan", lazy="selectin"
    )


class RoleTemplatePermission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "role_template_permissions"

    role_template_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("role_templates.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    role_template: Mapped[RoleTemplate] = relationship(back_populates="permission_links")
    permission: Mapped[Permission] = relationship(back_populates="template_links", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "role_template_id",
            "permission_id",
            name="role_template_permissions_template_permission_key",
        ),
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("role_templates.id", ondelete="SET NULL"), nullable=True
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

    organization = relationship("Organization", back_populates="roles")
    permission_links: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan", lazy="selectin"
    )
    membership_links = relationship("MembershipRole", back_populates="role")

    @property
    def permissions(self) -> list[Permission]:
        return [link.permission for link in self.permission_links]

    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="roles_org_id_id_key"),
        UniqueConstraint("organization_id", "code", name="roles_org_code_key"),
        Index("roles_org_is_active_idx", "organization_id", "is_active"),
        Index("roles_template_id_idx", "template_id"),
    )


class RolePermission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "role_permissions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False
    )
    granted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization_memberships.id", ondelete="SET NULL"), nullable=True
    )
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    role: Mapped[Role] = relationship(back_populates="permission_links")
    permission: Mapped[Permission] = relationship(back_populates="role_links", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "role_id",
            "permission_id",
            name="role_permissions_org_role_permission_key",
        ),
        Index("role_permissions_org_role_id_idx", "organization_id", "role_id"),
        Index("role_permissions_org_permission_id_idx", "organization_id", "permission_id"),
    )


class MembershipRole(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "membership_roles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organization_memberships.id", ondelete="CASCADE"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    assigned_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization_memberships.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    membership = relationship(
        "OrganizationMembership",
        back_populates="role_links",
        foreign_keys=[membership_id],
    )
    role = relationship("Role", back_populates="membership_links")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "membership_id",
            "role_id",
            name="membership_roles_org_membership_role_key",
        ),
        Index("membership_roles_org_membership_id_idx", "organization_id", "membership_id"),
        Index("membership_roles_org_role_id_idx", "organization_id", "role_id"),
    )
