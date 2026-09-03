import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, UUIDPrimaryKeyMixin


class CodeSequence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "code_sequences"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    last_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tenant = relationship("Tenant", back_populates="code_sequences")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "entity_type",
            name="code_sequences_tenant_id_entity_type_key",
        ),
        Index("code_sequences_tenant_id_entity_type_idx", "tenant_id", "entity_type"),
    )
