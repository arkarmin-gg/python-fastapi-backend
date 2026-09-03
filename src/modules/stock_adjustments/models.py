import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
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

from src.foundation_enums import DocumentStatus, StockAdjustmentReason
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class StockAdjustment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stock_adjustments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_no: Mapped[str] = mapped_column(String(80), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    reason: Mapped[StockAdjustmentReason] = str_enum_column(StockAdjustmentReason, nullable=False)
    status: Mapped[DocumentStatus] = str_enum_column(
        DocumentStatus,
        nullable=False,
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tenant = relationship("Tenant", back_populates="stock_adjustments")
    location = relationship("Location", back_populates="stock_adjustments")
    lines = relationship(
        "StockAdjustmentLine",
        back_populates="stock_adjustment",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_no",
            name="stock_adjustments_tenant_id_document_no_key",
        ),
        Index("stock_adjustments_tenant_id_location_id_idx", "tenant_id", "location_id"),
        Index("stock_adjustments_tenant_id_status_idx", "tenant_id", "status"),
    )


class StockAdjustmentLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_adjustment_lines"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    stock_adjustment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_adjustments.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    variant_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("variant_units.id", ondelete="RESTRICT"), nullable=False
    )
    stock_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stock_batches.id", ondelete="RESTRICT"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    conversion_to_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    unit_cost_base: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    manufactured_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    stock_adjustment = relationship("StockAdjustment", back_populates="lines")
    product_variant = relationship("ProductVariant", back_populates="stock_adjustment_lines")
    variant_unit = relationship("VariantUnit", back_populates="stock_adjustment_lines")
    stock_batch = relationship("StockBatch", back_populates="stock_adjustment_lines")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "stock_adjustment_id",
            "line_no",
            name="stock_adjustment_lines_adjustment_line_no_key",
        ),
        Index(
            "stock_adjustment_lines_tenant_id_product_variant_id_idx",
            "tenant_id",
            "product_variant_id",
        ),
        Index(
            "stock_adjustment_lines_tenant_id_variant_unit_id_idx",
            "tenant_id",
            "variant_unit_id",
        ),
        Index(
            "stock_adjustment_lines_tenant_id_stock_batch_id_idx",
            "tenant_id",
            "stock_batch_id",
        ),
    )
