from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import OrganizationStatus
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "organizations"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    status: Mapped[OrganizationStatus] = str_enum_column(
        OrganizationStatus,
        nullable=False,
        default=OrganizationStatus.ACTIVE,
        server_default=OrganizationStatus.ACTIVE.value,
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    memberships = relationship("OrganizationMembership", back_populates="organization")
    roles = relationship("Role", back_populates="organization")

    __table_args__ = (
        Index("organizations_status_idx", "status"),
        Index("organizations_deleted_at_idx", "deleted_at"),
    )
