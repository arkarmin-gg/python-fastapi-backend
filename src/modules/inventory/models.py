import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import SourceType, StockBatchStatus, StockMovementType
from src.models import Base, UUIDPrimaryKeyMixin, str_enum_column


class StockBatch(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_batches"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[SourceType] = str_enum_column(SourceType, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    manufactured_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    initial_quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    unit_cost_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    conversion_to_base: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    status: Mapped[StockBatchStatus] = str_enum_column(
        StockBatchStatus,
        nullable=False,
        default=StockBatchStatus.ACTIVE,
        server_default=StockBatchStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tenant = relationship("Tenant", back_populates="stock_batches")
    product_variant = relationship("ProductVariant", back_populates="stock_batches")
    supplier = relationship("Supplier", back_populates="stock_batches")
    movements = relationship("StockMovement", back_populates="stock_batch")
    balances = relationship("StockBalance", back_populates="stock_batch")
    stock_adjustment_lines = relationship("StockAdjustmentLine", back_populates="stock_batch")
    stock_count_lines = relationship("StockCountLine", back_populates="stock_batch")
    stock_transfer_lines = relationship("StockTransferLine", back_populates="stock_batch")
    repack_order_inputs = relationship("RepackOrderInput", back_populates="stock_batch")
    repack_order_outputs = relationship("RepackOrderOutput", back_populates="created_stock_batch")
    sales_invoice_line_costs = relationship("SalesInvoiceLineCost", back_populates="stock_batch")
    product_variant_sku = association_proxy("product_variant", "sku")
    product_variant_name = association_proxy("product_variant", "name")
    supplier_name = association_proxy("supplier", "name")

    __table_args__ = (
        Index(
            "stock_batches_tenant_id_product_variant_id_received_at_idx",
            "tenant_id",
            "product_variant_id",
            "received_at",
        ),
        Index(
            "stock_batches_tenant_id_variant_expiry_date_idx",
            "tenant_id",
            "product_variant_id",
            "expiry_date",
        ),
        Index("stock_batches_tenant_id_supplier_id_idx", "tenant_id", "supplier_id"),
        Index(
            "stock_batches_tenant_id_source_type_source_id_idx",
            "tenant_id",
            "source_type",
            "source_id",
        ),
    )


class StockMovement(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_movements"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    movement_type: Mapped[StockMovementType] = str_enum_column(StockMovementType, nullable=False)
    source_type: Mapped[SourceType] = str_enum_column(SourceType, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    source_line_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_batches.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    unit_cost_base: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tenant = relationship("Tenant", back_populates="stock_movements")
    product_variant = relationship("ProductVariant", back_populates="stock_movements")
    stock_batch = relationship("StockBatch", back_populates="movements")
    sales_invoice_line_cost = relationship(
        "SalesInvoiceLineCost", back_populates="stock_movement", uselist=False
    )
    stock_count_line = relationship(
        "StockCountLine",
        back_populates="adjustment_movement",
        uselist=False,
    )
    location = relationship("Location", back_populates="stock_movements")
    posted_by_user = relationship("User", back_populates="stock_movements")
    product_variant_sku = association_proxy("product_variant", "sku")
    product_variant_name = association_proxy("product_variant", "name")
    location_name = association_proxy("location", "name")
    posted_by_name = association_proxy("posted_by_user", "name")

    @property
    def stock_batch_lot_number(self) -> str | None:
        return self.stock_batch.lot_number

    @property
    def stock_batch_received_at(self) -> datetime:
        return self.stock_batch.received_at

    @property
    def stock_batch_expiry_date(self) -> date | None:
        return self.stock_batch.expiry_date

    __table_args__ = (
        Index(
            "stock_movements_tenant_variant_location_posted_idx",
            "tenant_id",
            "product_variant_id",
            "location_id",
            "posted_at",
        ),
        Index(
            "stock_movements_tenant_id_stock_batch_id_posted_at_idx",
            "tenant_id",
            "stock_batch_id",
            "posted_at",
        ),
        Index(
            "stock_movements_tenant_id_source_type_source_id_idx",
            "tenant_id",
            "source_type",
            "source_id",
        ),
        Index(
            "stock_movements_tenant_id_movement_type_posted_at_idx",
            "tenant_id",
            "movement_type",
            "posted_at",
        ),
    )


class StockBalance(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "stock_balances"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_batches.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_base: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0"), server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tenant = relationship("Tenant", back_populates="stock_balances")
    product_variant = relationship("ProductVariant", back_populates="stock_balances")
    location = relationship("Location", back_populates="stock_balances")
    stock_batch = relationship("StockBatch", back_populates="balances")
    product_variant_sku = association_proxy("product_variant", "sku")
    product_variant_name = association_proxy("product_variant", "name")
    location_name = association_proxy("location", "name")
    unit_id = association_proxy("product_variant", "base_unit_id")
    unit_code = association_proxy("product_variant", "base_unit_code")
    unit_name = association_proxy("product_variant", "base_unit_name")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_variant_id",
            "location_id",
            "stock_batch_id",
            name="stock_balances_tenant_variant_location_batch_key",
        ),
        Index(
            "stock_balances_tenant_id_product_variant_id_location_id_idx",
            "tenant_id",
            "product_variant_id",
            "location_id",
        ),
        Index("stock_balances_tenant_id_stock_batch_id_idx", "tenant_id", "stock_batch_id"),
    )

    @property
    def stock_batch_lot_number(self) -> str | None:
        return self.stock_batch.lot_number

    @property
    def stock_batch_received_at(self) -> datetime:
        return self.stock_batch.received_at

    @property
    def stock_batch_expiry_date(self) -> date | None:
        return self.stock_batch.expiry_date
