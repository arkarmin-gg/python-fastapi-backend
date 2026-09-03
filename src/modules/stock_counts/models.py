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


class StockCount(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "stock_counts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_no: Mapped[str] = mapped_column(String(80), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    counted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    counted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[DocumentStatus] = str_enum_column(
        DocumentStatus,
        nullable=False,
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    tenant = relationship("Tenant", back_populates="stock_counts")
    location = relationship("Location", back_populates="stock_counts")
    counted_by_user = relationship(
        "User", foreign_keys=[counted_by], back_populates="counted_stock_counts"
    )
    approved_by_user = relationship(
        "User", foreign_keys=[approved_by], back_populates="approved_stock_counts"
    )
    posted_by_user = relationship(
        "User", foreign_keys=[posted_by], back_populates="posted_stock_counts"
    )
    lines = relationship(
        "StockCountLine",
        back_populates="stock_count",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "document_no", name="stock_counts_tenant_id_document_no_key"),
        Index(
            "stock_counts_tenant_id_location_counted_at_idx",
            "tenant_id",
            "location_id",
            "counted_at",
        ),
        Index("stock_counts_tenant_id_status_idx", "tenant_id", "status"),
    )


class StockCountLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_count_lines"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    stock_count_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_counts.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_batches.id", ondelete="RESTRICT"), nullable=False
    )
    expected_quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    counted_quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    variance_quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    adjustment_movement_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stock_movements.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    stock_count = relationship("StockCount", back_populates="lines")
    product_variant = relationship("ProductVariant", back_populates="stock_count_lines")
    stock_batch = relationship("StockBatch", back_populates="stock_count_lines")
    adjustment_movement = relationship("StockMovement", back_populates="stock_count_line")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "stock_count_id",
            "line_no",
            name="stock_count_lines_count_line_no_key",
        ),
        Index(
            "stock_count_lines_tenant_variant_batch_idx",
            "tenant_id",
            "product_variant_id",
            "stock_batch_id",
        ),
        Index(
            "stock_count_lines_tenant_adjustment_movement_idx",
            "tenant_id",
            "adjustment_movement_id",
        ),
    )
