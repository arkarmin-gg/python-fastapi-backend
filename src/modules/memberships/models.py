from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import MembershipStatus
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class OrganizationMembership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organization_memberships"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[MembershipStatus] = str_enum_column(
        MembershipStatus,
        nullable=False,
        default=MembershipStatus.ACTIVE,
        server_default=MembershipStatus.ACTIVE.value,
    )
    invited_by_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization_memberships.id", ondelete="SET NULL"), nullable=True
    )
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    organization = relationship("Organization", back_populates="memberships")
    user = relationship("User", back_populates="memberships")
    role_links = relationship(
        "MembershipRole",
        back_populates="membership",
        foreign_keys="MembershipRole.membership_id",
        overlaps="membership_links,role",
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('invited', 'active', 'suspended', 'inactive', 'removed')",
            name="status_valid",
        ),
        UniqueConstraint("organization_id", "id", name="organization_memberships_org_id_id_key"),
        UniqueConstraint(
            "organization_id", "user_id", name="organization_memberships_org_user_key"
        ),
        Index("organization_memberships_org_status_idx", "organization_id", "status"),
        Index("organization_memberships_user_id_idx", "user_id"),
    )
