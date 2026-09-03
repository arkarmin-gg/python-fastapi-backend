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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import (
    CustomerLedgerEntryType,
    DocumentStatus,
    PaymentMethod,
    SourceType,
)
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class CustomerPayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "customer_payments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_no: Mapped[str] = mapped_column(String(80), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    payment_date: Mapped[date] = mapped_column(Date, nullable=False)
    payment_method: Mapped[PaymentMethod] = str_enum_column(
        PaymentMethod,
        nullable=False,
        default=PaymentMethod.CASH,
        server_default=PaymentMethod.CASH.value,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    status: Mapped[DocumentStatus] = str_enum_column(
        DocumentStatus,
        nullable=False,
        default=DocumentStatus.DRAFT,
        server_default=DocumentStatus.DRAFT.value,
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
    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reversed_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reversal_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    tenant = relationship("Tenant", back_populates="customer_payments")
    customer = relationship("Customer", back_populates="customer_payments")
    allocations = relationship(
        "CustomerPaymentAllocation",
        back_populates="customer_payment",
        cascade="all, delete-orphan",
    )
    pos_checkout = relationship(
        "PosCheckout",
        back_populates="customer_payment",
        uselist=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_no",
            name="customer_payments_tenant_id_document_no_key",
        ),
        Index(
            "customer_payments_tenant_id_customer_id_payment_date_idx",
            "tenant_id",
            "customer_id",
            "payment_date",
        ),
        Index("customer_payments_tenant_id_status_idx", "tenant_id", "status"),
        Index(
            "customer_payments_tenant_id_idempotency_key_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=idempotency_key.is_not(None),
        ),
    )


class CustomerPaymentAllocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "customer_payment_allocations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    customer_payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customer_payments.id", ondelete="CASCADE"), nullable=False
    )
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sales_invoices.id", ondelete="RESTRICT"), nullable=False
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)

    customer_payment = relationship("CustomerPayment", back_populates="allocations")
    sales_invoice = relationship("SalesInvoice", back_populates="customer_payment_allocations")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "customer_payment_id",
            "sales_invoice_id",
            name="customer_payment_allocations_payment_invoice_key",
        ),
        Index(
            "customer_payment_allocations_tenant_id_sales_invoice_id_idx",
            "tenant_id",
            "sales_invoice_id",
        ),
    )


class CustomerLedgerEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "customer_ledger_entries"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    entry_type: Mapped[CustomerLedgerEntryType] = str_enum_column(
        CustomerLedgerEntryType,
        nullable=False,
    )
    debit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    credit_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    balance_effect: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    source_type: Mapped[SourceType] = str_enum_column(SourceType, nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    posted_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    tenant = relationship("Tenant", back_populates="customer_ledger_entries")
    customer = relationship("Customer", back_populates="customer_ledger_entries")

    __table_args__ = (
        Index(
            "customer_ledger_entries_tenant_id_customer_id_posted_at_idx",
            "tenant_id",
            "customer_id",
            "posted_at",
        ),
        Index(
            "customer_ledger_entries_tenant_id_source_type_source_id_idx",
            "tenant_id",
            "source_type",
            "source_id",
        ),
    )


class CustomerBalance(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "customer_balances"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("customers.id", ondelete="RESTRICT"), nullable=False
    )
    balance_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tenant = relationship("Tenant", back_populates="customer_balances")
    customer = relationship("Customer", back_populates="customer_balance")

    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_id", name="customer_balances_tenant_customer_key"),
    )
