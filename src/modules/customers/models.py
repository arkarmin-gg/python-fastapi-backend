import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import CustomerType, PartyStatus
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class Customer(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customers"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    customer_type: Mapped[CustomerType] = str_enum_column(
        CustomerType,
        nullable=False,
        default=CustomerType.RETAIL,
        server_default=CustomerType.RETAIL.value,
    )
    price_level_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("price_levels.id", ondelete="SET NULL"), nullable=True
    )
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    credit_limit: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    status: Mapped[PartyStatus] = str_enum_column(
        PartyStatus,
        nullable=False,
        default=PartyStatus.ACTIVE,
        server_default=PartyStatus.ACTIVE.value,
    )

    tenant = relationship("Tenant", back_populates="customers")
    price_level = relationship("PriceLevel", back_populates="customers")
    price_rules = relationship("PriceRule", back_populates="customer")
    sales_invoices = relationship("SalesInvoice", back_populates="customer")
    customer_payments = relationship("CustomerPayment", back_populates="customer")
    customer_ledger_entries = relationship("CustomerLedgerEntry", back_populates="customer")
    customer_balance = relationship("CustomerBalance", back_populates="customer", uselist=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="customers_tenant_id_code_key"),
        Index("customers_tenant_id_name_idx", "tenant_id", "name"),
        Index("customers_tenant_id_price_level_id_idx", "tenant_id", "price_level_id"),
    )
