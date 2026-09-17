from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
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
    __table_args__ = (
        Index("permissions_module_idx", "module"),
        Index("permissions_module_is_active_idx", "module", "is_active"),
    )


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
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
    membership_links = relationship(
        "MembershipRole",
        back_populates="role",
        overlaps="membership,role_links",
    )

    @property
    def permissions(self) -> list[Permission]:
        return [link.permission for link in self.permission_links]

    __table_args__ = (
        UniqueConstraint("organization_id", "id", name="roles_org_id_id_key"),
        UniqueConstraint("organization_id", "code", name="roles_org_code_key"),
        Index("roles_org_is_active_idx", "organization_id", "is_active"),
    )


class RolePermission(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "role_permissions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    permission_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("permissions.id", ondelete="RESTRICT"), nullable=False
    )
    granted_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    role: Mapped[Role] = relationship(
        back_populates="permission_links",
        foreign_keys=[organization_id, role_id],
    )
    permission: Mapped[Permission] = relationship(back_populates="role_links", lazy="joined")

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "role_id",
            "permission_id",
            name="role_permissions_org_role_permission_key",
        ),
        ForeignKeyConstraint(
            ["organization_id", "role_id"],
            ["roles.organization_id", "roles.id"],
            name="role_permissions_org_role_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "granted_by_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            name="role_permissions_org_granted_by_membership_fkey",
            ondelete="RESTRICT",
        ),
        Index("role_permissions_org_role_idx", "organization_id", "role_id"),
        Index("role_permissions_org_permission_idx", "organization_id", "permission_id"),
    )


class MembershipRole(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "membership_roles"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    assigned_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    membership = relationship(
        "OrganizationMembership",
        back_populates="role_links",
        foreign_keys=[organization_id, membership_id],
        overlaps="membership_links,role",
    )
    role = relationship(
        "Role",
        back_populates="membership_links",
        foreign_keys=[organization_id, role_id],
        overlaps="membership,role_links",
    )

    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "membership_id",
            "role_id",
            name="membership_roles_org_membership_role_key",
        ),
        ForeignKeyConstraint(
            ["organization_id", "membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            name="membership_roles_org_membership_fkey",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["organization_id", "assigned_by_membership_id"],
            ["organization_memberships.organization_id", "organization_memberships.id"],
            name="membership_roles_org_assigned_by_membership_fkey",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_id", "role_id"],
            ["roles.organization_id", "roles.id"],
            name="membership_roles_org_role_fkey",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > assigned_at",
            name="expires_after_assigned",
        ),
        Index("membership_roles_org_membership_idx", "organization_id", "membership_id"),
        Index("membership_roles_org_role_idx", "organization_id", "role_id"),
        Index("membership_roles_org_expires_at_idx", "organization_id", "expires_at"),
    )
