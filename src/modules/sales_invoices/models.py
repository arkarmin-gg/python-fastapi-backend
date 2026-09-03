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


class SalesInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sales_invoices"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_no: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    price_level_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("price_levels.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[DocumentStatus] = str_enum_column(
        DocumentStatus,
        nullable=False,
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
    )
    subtotal_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    discount_amount: Mapped[Decimal] = mapped_column(
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
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    gross_profit: Mapped[Decimal] = mapped_column(
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
        Uuid, ForeignKey("sales_invoices.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tenant = relationship("Tenant", back_populates="sales_invoices")
    customer = relationship("Customer", back_populates="sales_invoices")
    location = relationship("Location", back_populates="sales_invoices")
    price_level = relationship("PriceLevel", back_populates="sales_invoices")
    posted_by_user = relationship("User", foreign_keys=[posted_by])

    @property
    def posted_by_name(self) -> str | None:
        return self.posted_by_user.name if self.posted_by_user is not None else None

    lines = relationship(
        "SalesInvoiceLine",
        back_populates="sales_invoice",
        cascade="all, delete-orphan",
    )
    customer_payment_allocations = relationship(
        "CustomerPaymentAllocation",
        back_populates="sales_invoice",
    )
    pos_checkout = relationship(
        "PosCheckout",
        back_populates="sales_invoice",
        uselist=False,
    )
    reversal_of = relationship("SalesInvoice", remote_side="SalesInvoice.id")

    __table_args__ = (
        UniqueConstraint("tenant_id", "document_no", name="sales_invoices_tenant_document_key"),
        Index(
            "sales_invoices_tenant_id_customer_id_invoice_date_idx",
            "tenant_id",
            "customer_id",
            "invoice_date",
        ),
        Index(
            "sales_invoices_tenant_id_location_id_invoice_date_idx",
            "tenant_id",
            "location_id",
            "invoice_date",
        ),
        Index("sales_invoices_tenant_id_status_idx", "tenant_id", "status"),
    )


class SalesInvoiceLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_invoice_lines"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sales_invoices.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False
    )
    variant_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("variant_units.id", ondelete="RESTRICT"), nullable=False
    )
    source_location_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    conversion_to_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    measured_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    line_total: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    gross_profit: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    price_rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("price_rules.id", ondelete="SET NULL"), nullable=True
    )

    sales_invoice = relationship("SalesInvoice", back_populates="lines")
    product_variant = relationship("ProductVariant", back_populates="sales_invoice_lines")
    variant_unit = relationship("VariantUnit", back_populates="sales_invoice_lines")
    source_location = relationship("Location")
    price_rule = relationship("PriceRule", back_populates="sales_invoice_lines")
    costs = relationship(
        "SalesInvoiceLineCost",
        back_populates="sales_invoice_line",
        cascade="all, delete-orphan",
    )
    locations = relationship(
        "SalesInvoiceLineLocation",
        back_populates="sales_invoice_line",
        cascade="all, delete-orphan",
        order_by="SalesInvoiceLineLocation.created_at.asc()",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "sales_invoice_id",
            "line_no",
            name="sales_invoice_lines_invoice_line_no_key",
        ),
        Index(
            "sales_invoice_lines_tenant_id_product_variant_id_idx",
            "tenant_id",
            "product_variant_id",
        ),
        Index(
            "sales_invoice_lines_tenant_id_source_location_id_idx",
            "tenant_id",
            "source_location_id",
        ),
    )


class SalesInvoiceLineCost(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "sales_invoice_line_costs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sales_invoice_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sales_invoice_lines.id", ondelete="CASCADE"), nullable=False
    )
    stock_batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_batches.id", ondelete="RESTRICT"), nullable=False
    )
    stock_movement_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("stock_movements.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    unit_cost_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)

    tenant = relationship("Tenant", back_populates="sales_invoice_line_costs")
    sales_invoice_line = relationship("SalesInvoiceLine", back_populates="costs")
    stock_batch = relationship("StockBatch", back_populates="sales_invoice_line_costs")
    stock_movement = relationship("StockMovement", back_populates="sales_invoice_line_cost")

    __table_args__ = (
        Index(
            "sales_invoice_line_costs_tenant_id_sales_invoice_line_id_idx",
            "tenant_id",
            "sales_invoice_line_id",
        ),
        Index(
            "sales_invoice_line_costs_tenant_id_stock_batch_id_idx",
            "tenant_id",
            "stock_batch_id",
        ),
    )


class SalesInvoiceLineLocation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "sales_invoice_line_locations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sales_invoice_line_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sales_invoice_lines.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    quantity_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)

    tenant = relationship("Tenant", back_populates="sales_invoice_line_locations")
    sales_invoice_line = relationship("SalesInvoiceLine", back_populates="locations")
    location = relationship("Location", back_populates="sales_invoice_line_locations")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "sales_invoice_line_id",
            "location_id",
            name="sales_invoice_line_locations_line_location_key",
        ),
        Index(
            "sinv_line_locations_tenant_id_line_id_idx",
            "tenant_id",
            "sales_invoice_line_id",
        ),
        Index(
            "sinv_line_locations_tenant_id_location_id_idx",
            "tenant_id",
            "location_id",
        ),
    )
