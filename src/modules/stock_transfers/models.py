import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import DocumentStatus
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class StockTransfer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stock_transfers"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_no: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[DocumentStatus] = str_enum_column(
        DocumentStatus,
        nullable=False,
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stock_transfers.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tenant = relationship("Tenant", back_populates="stock_transfers")
    lines = relationship(
        "StockTransferLine", back_populates="stock_transfer", cascade="all, delete-orphan"
    )
    reversal_of = relationship("StockTransfer", remote_side="StockTransfer.id")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "document_no", name="stock_transfers_tenant_id_document_no_key"
        ),
        Index("stock_transfers_tenant_id_status_idx", "tenant_id", "status"),
    )


class StockTransferLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_transfer_lines"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    stock_transfer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_transfers.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    variant_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("variant_units.id", ondelete="RESTRICT"), nullable=False
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_batches.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    conversion_to_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    from_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    to_location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )

    stock_transfer = relationship("StockTransfer", back_populates="lines")
    product_variant = relationship("ProductVariant", back_populates="stock_transfer_lines")
    variant_unit = relationship("VariantUnit", back_populates="stock_transfer_lines")
    stock_batch = relationship("StockBatch", back_populates="stock_transfer_lines")
    from_location = relationship(
        "Location", foreign_keys=[from_location_id], back_populates="stock_transfer_lines_from"
    )
    to_location = relationship(
        "Location", foreign_keys=[to_location_id], back_populates="stock_transfer_lines_to"
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "stock_transfer_id",
            "line_no",
            name="stock_transfer_lines_transfer_line_no_key",
        ),
        Index(
            "stock_transfer_lines_tenant_id_from_location_id_idx", "tenant_id", "from_location_id"
        ),
        Index("stock_transfer_lines_tenant_id_to_location_id_idx", "tenant_id", "to_location_id"),
        Index(
            "stock_transfer_lines_tenant_id_product_variant_id_idx",
            "tenant_id",
            "product_variant_id",
        ),
        Index(
            "stock_transfer_lines_tenant_id_variant_unit_id_idx",
            "tenant_id",
            "variant_unit_id",
        ),
    )
