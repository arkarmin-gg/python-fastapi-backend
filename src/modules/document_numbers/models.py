import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, UUIDPrimaryKeyMixin


class DocumentSequence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "document_sequences"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_type: Mapped[str] = mapped_column(String(40), nullable=False)
    period: Mapped[str] = mapped_column(String(6), nullable=False)
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

    tenant = relationship("Tenant", back_populates="document_sequences")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_type",
            "period",
            name="document_sequences_tenant_id_document_type_period_key",
        ),
        Index(
            "document_sequences_tenant_id_document_type_period_idx",
            "tenant_id",
            "document_type",
            "period",
        ),
    )
