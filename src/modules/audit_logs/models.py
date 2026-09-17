from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.foundation_enums import ActorType
from src.models import Base, UUIDPrimaryKeyMixin, str_enum_column


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True
    )
    actor_type: Mapped[ActorType] = str_enum_column(
        ActorType,
        nullable=False,
        default=ActorType.USER,
        server_default=ActorType.USER.value,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organization_memberships.id", ondelete="SET NULL"), nullable=True
    )
    actor_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    before_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(INET, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user', 'system', 'service', 'api_key')",
            name="actor_type_valid",
        ),
        Index(
            "audit_logs_org_entity_idx",
            "organization_id",
            "entity_type",
            "entity_id",
        ),
        Index(
            "audit_logs_org_membership_created_at_idx",
            "organization_id",
            "actor_membership_id",
            "created_at",
        ),
        Index(
            "audit_logs_org_user_created_at_idx",
            "organization_id",
            "actor_user_id",
            "created_at",
        ),
        Index("audit_logs_org_created_at_idx", "organization_id", "created_at"),
        Index(
            "audit_logs_org_action_created_at_idx",
            "organization_id",
            "action",
            "created_at",
        ),
        Index("audit_logs_actor_user_id_idx", "actor_user_id"),
        Index("audit_logs_request_id_idx", "request_id"),
        Index("audit_logs_trace_id_idx", "trace_id"),
    )
