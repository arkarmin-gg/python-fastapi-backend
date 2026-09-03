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

from src.foundation_enums import DocumentStatus
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class RepackOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "repack_orders"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_no: Mapped[str] = mapped_column(String(80), nullable=False)
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[DocumentStatus] = str_enum_column(
        DocumentStatus,
        nullable=False,
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    performed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employees.id", ondelete="SET NULL"), nullable=True
    )
    total_input_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_output_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    waste_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_input_quantity_base: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_output_quantity_base: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0"), server_default="0"
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
        Uuid, ForeignKey("repack_orders.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tenant = relationship("Tenant", back_populates="repack_orders")
    location = relationship("Location", back_populates="repack_orders")
    performed_by_employee = relationship("Employee", back_populates="repack_orders")
    inputs = relationship(
        "RepackOrderInput",
        back_populates="repack_order",
        cascade="all, delete-orphan",
    )
    outputs = relationship(
        "RepackOrderOutput",
        back_populates="repack_order",
        cascade="all, delete-orphan",
    )
    reversal_of = relationship("RepackOrder", remote_side="RepackOrder.id")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_no",
            name="repack_orders_tenant_id_document_no_key",
        ),
        Index("repack_orders_tenant_id_location_id_idx", "tenant_id", "location_id"),
        Index("repack_orders_tenant_id_performed_by_idx", "tenant_id", "performed_by"),
        Index("repack_orders_tenant_id_status_idx", "tenant_id", "status"),
    )


class RepackOrderInput(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "repack_order_inputs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    repack_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repack_orders.id", ondelete="CASCADE"), nullable=False
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
    unit_cost_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)

    repack_order = relationship("RepackOrder", back_populates="inputs")
    product_variant = relationship("ProductVariant", back_populates="repack_order_inputs")
    variant_unit = relationship("VariantUnit", back_populates="repack_order_inputs")
    stock_batch = relationship("StockBatch", back_populates="repack_order_inputs")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "repack_order_id",
            "line_no",
            name="repack_order_inputs_order_line_no_key",
        ),
        Index("repack_order_inputs_tenant_id_stock_batch_id_idx", "tenant_id", "stock_batch_id"),
        Index(
            "repack_order_inputs_tenant_id_product_variant_id_idx",
            "tenant_id",
            "product_variant_id",
        ),
        Index(
            "repack_order_inputs_tenant_id_variant_unit_id_idx",
            "tenant_id",
            "variant_unit_id",
        ),
    )


class RepackOrderOutput(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "repack_order_outputs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    repack_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("repack_orders.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    variant_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("variant_units.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    conversion_to_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    allocated_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    unit_cost_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_stock_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stock_batches.id", ondelete="SET NULL"), nullable=True
    )

    repack_order = relationship("RepackOrder", back_populates="outputs")
    product_variant = relationship("ProductVariant", back_populates="repack_order_outputs")
    variant_unit = relationship("VariantUnit", back_populates="repack_order_outputs")
    created_stock_batch = relationship("StockBatch", back_populates="repack_order_outputs")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "repack_order_id",
            "line_no",
            name="repack_order_outputs_order_line_no_key",
        ),
        Index(
            "repack_order_outputs_tenant_created_stock_batch_idx",
            "tenant_id",
            "created_stock_batch_id",
        ),
        Index(
            "repack_order_outputs_tenant_id_product_variant_id_idx",
            "tenant_id",
            "product_variant_id",
        ),
        Index(
            "repack_order_outputs_tenant_id_variant_unit_id_idx",
            "tenant_id",
            "variant_unit_id",
        ),
    )
