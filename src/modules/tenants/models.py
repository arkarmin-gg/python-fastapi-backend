from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import TenantStatus
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    code: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    legal_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="MMK", server_default="MMK"
    )
    timezone: Mapped[str] = mapped_column(
        String(80), nullable=False, default="Asia/Yangon", server_default="Asia/Yangon"
    )
    locale: Mapped[str] = mapped_column(
        String(20), nullable=False, default="my-MM", server_default="my-MM"
    )
    status: Mapped[TenantStatus] = str_enum_column(
        TenantStatus,
        nullable=False,
        default=TenantStatus.ACTIVE,
        server_default=TenantStatus.ACTIVE.value,
    )

    employees = relationship("Employee", back_populates="tenant")
    users = relationship("User", back_populates="tenant")
    code_sequences = relationship("CodeSequence", back_populates="tenant")
    document_sequences = relationship("DocumentSequence", back_populates="tenant")
    roles = relationship("Role", back_populates="tenant")
    product_categories = relationship("ProductCategory", back_populates="tenant")
    catalog_items = relationship("CatalogItem", back_populates="tenant")
    product_variants = relationship("ProductVariant", back_populates="tenant")
    variant_units = relationship("VariantUnit", back_populates="tenant")
    variant_barcodes = relationship("VariantBarcode", back_populates="tenant")
    variant_pos_profiles = relationship("VariantPosProfile", back_populates="tenant")
    variant_location_settings = relationship("VariantLocationSetting", back_populates="tenant")
    price_levels = relationship("PriceLevel", back_populates="tenant")
    customers = relationship("Customer", back_populates="tenant")
    customer_payments = relationship("CustomerPayment", back_populates="tenant")
    customer_ledger_entries = relationship("CustomerLedgerEntry", back_populates="tenant")
    customer_balances = relationship("CustomerBalance", back_populates="tenant")
    pos_checkouts = relationship("PosCheckout", back_populates="tenant")
    suppliers = relationship("Supplier", back_populates="tenant")
    supplier_payments = relationship("SupplierPayment", back_populates="tenant")
    supplier_ledger_entries = relationship("SupplierLedgerEntry", back_populates="tenant")
    supplier_balances = relationship("SupplierBalance", back_populates="tenant")
    price_rules = relationship("PriceRule", back_populates="tenant")
    locations = relationship("Location", back_populates="tenant")
    location_assignments = relationship("LocationAssignment", back_populates="tenant")
    purchase_invoices = relationship("PurchaseInvoice", back_populates="tenant")
    stock_adjustments = relationship("StockAdjustment", back_populates="tenant")
    stock_counts = relationship("StockCount", back_populates="tenant")
    stock_transfers = relationship("StockTransfer", back_populates="tenant")
    repack_orders = relationship("RepackOrder", back_populates="tenant")
    sales_invoices = relationship("SalesInvoice", back_populates="tenant")
    sales_invoice_line_costs = relationship("SalesInvoiceLineCost", back_populates="tenant")
    sales_invoice_line_locations = relationship("SalesInvoiceLineLocation", back_populates="tenant")
    stock_batches = relationship("StockBatch", back_populates="tenant")
    stock_movements = relationship("StockMovement", back_populates="tenant")
    stock_balances = relationship("StockBalance", back_populates="tenant")

    __table_args__ = (
        Index("tenants_code_idx", "code"),
        Index("tenants_status_idx", "status"),
    )
