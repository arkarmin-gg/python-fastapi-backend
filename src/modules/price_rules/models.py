import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class PriceRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "price_rules"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    variant_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("variant_units.id", ondelete="RESTRICT"), nullable=False
    )
    price_level_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("price_levels.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="CASCADE"), nullable=True
    )
    min_quantity: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    currency_code: Mapped[str] = mapped_column(
        String(3), nullable=False, default="MMK", server_default="MMK"
    )
    unit_price: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="price_rules")
    product_variant = relationship("ProductVariant", back_populates="price_rules")
    variant_unit = relationship("VariantUnit")
    price_level = relationship("PriceLevel", back_populates="price_rules")
    customer = relationship("Customer", back_populates="price_rules")
    sales_invoice_lines = relationship("SalesInvoiceLine", back_populates="price_rule")

    __table_args__ = (
        Index(
            "price_rules_variant_scope_effective_from_idx",
            "tenant_id",
            "product_variant_id",
            "variant_unit_id",
            "price_level_id",
            "effective_from",
        ),
        Index("price_rules_tenant_id_customer_id_idx", "tenant_id", "customer_id"),
    )
