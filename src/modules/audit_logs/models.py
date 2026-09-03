import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "audit_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    before_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        Index(
            "audit_logs_tenant_id_entity_type_entity_id_idx",
            "tenant_id",
            "entity_type",
            "entity_id",
        ),
        Index(
            "audit_logs_tenant_id_actor_user_id_created_at_idx",
            "tenant_id",
            "actor_user_id",
            "created_at",
        ),
        Index("audit_logs_tenant_id_created_at_idx", "tenant_id", "created_at"),
    )
