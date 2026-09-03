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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import (
    DocumentStatus,
    LandedCostAllocationMethod,
    PurchaseLandedCostType,
)
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class PurchaseInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchase_invoices"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_no: Mapped[str] = mapped_column(String(80), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    supplier_invoice_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[DocumentStatus] = str_enum_column(
        DocumentStatus,
        nullable=False,
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    landed_cost_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    balance_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reversal_of_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("purchase_invoices.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tenant = relationship("Tenant", back_populates="purchase_invoices")
    supplier = relationship("Supplier", back_populates="purchase_invoices")
    posted_by_user = relationship("User", foreign_keys=[posted_by])

    @property
    def posted_by_name(self) -> str | None:
        return self.posted_by_user.name if self.posted_by_user is not None else None

    lines = relationship(
        "PurchaseInvoiceLine",
        back_populates="purchase_invoice",
        cascade="all, delete-orphan",
    )
    landed_costs = relationship(
        "PurchaseLandedCost",
        back_populates="purchase_invoice",
        cascade="all, delete-orphan",
    )
    supplier_payment_allocations = relationship(
        "SupplierPaymentAllocation",
        back_populates="purchase_invoice",
    )
    reversal_of = relationship("PurchaseInvoice", remote_side="PurchaseInvoice.id")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_no",
            name="purchase_invoices_tenant_id_document_no_key",
        ),
        Index(
            "purchase_invoices_tenant_id_supplier_id_invoice_date_idx",
            "tenant_id",
            "supplier_id",
            "invoice_date",
        ),
        Index("purchase_invoices_tenant_id_status_idx", "tenant_id", "status"),
    )


class PurchaseInvoiceLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_invoice_lines"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    purchase_invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchase_invoices.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    variant_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("variant_units.id", ondelete="RESTRICT"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    conversion_to_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    measured_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    line_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    allocated_landed_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_line_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    unit_cost_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    manufactured_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_stock_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("stock_batches.id", ondelete="SET NULL"), nullable=True
    )

    purchase_invoice = relationship("PurchaseInvoice", back_populates="lines")
    product_variant = relationship("ProductVariant", back_populates="purchase_invoice_lines")
    variant_unit = relationship("VariantUnit", back_populates="purchase_invoice_lines")
    location = relationship("Location", back_populates="purchase_invoice_lines")
    created_stock_batch = relationship(
        "StockBatch",
        primaryjoin="foreign(PurchaseInvoiceLine.created_stock_batch_id) == StockBatch.id",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "purchase_invoice_id",
            "line_no",
            name="purchase_invoice_lines_invoice_line_no_key",
        ),
        Index(
            "purchase_invoice_lines_tenant_id_product_variant_id_idx",
            "tenant_id",
            "product_variant_id",
        ),
        Index(
            "purchase_invoice_lines_tenant_id_location_id_idx",
            "tenant_id",
            "location_id",
        ),
    )


class PurchaseLandedCost(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_landed_costs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    purchase_invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchase_invoices.id", ondelete="CASCADE"), nullable=False
    )
    cost_type: Mapped[PurchaseLandedCostType] = str_enum_column(
        PurchaseLandedCostType, nullable=False
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    allocation_method: Mapped[LandedCostAllocationMethod] = str_enum_column(
        LandedCostAllocationMethod,
        nullable=False,
        default=LandedCostAllocationMethod.BY_VALUE,
        server_default=LandedCostAllocationMethod.BY_VALUE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    purchase_invoice = relationship("PurchaseInvoice", back_populates="landed_costs")

    __table_args__ = (
        Index(
            "purchase_landed_costs_tenant_id_purchase_invoice_id_idx",
            "tenant_id",
            "purchase_invoice_id",
        ),
    )
