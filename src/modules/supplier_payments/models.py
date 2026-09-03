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
    DocumentStatus,
    PaymentMethod,
    SourceType,
    SupplierLedgerEntryType,
)
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class SupplierPayment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "supplier_payments"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    document_no: Mapped[str] = mapped_column(String(80), nullable=False)
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
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

    tenant = relationship("Tenant", back_populates="supplier_payments")
    supplier = relationship("Supplier", back_populates="supplier_payments")
    allocations = relationship(
        "SupplierPaymentAllocation",
        back_populates="supplier_payment",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "document_no",
            name="supplier_payments_tenant_id_document_no_key",
        ),
        Index(
            "supplier_payments_tenant_id_supplier_id_payment_date_idx",
            "tenant_id",
            "supplier_id",
            "payment_date",
        ),
        Index("supplier_payments_tenant_id_status_idx", "tenant_id", "status"),
        Index(
            "supplier_payments_tenant_id_idempotency_key_key",
            "tenant_id",
            "idempotency_key",
            unique=True,
            postgresql_where=idempotency_key.is_not(None),
        ),
    )


class SupplierPaymentAllocation(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_payment_allocations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    supplier_payment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("supplier_payments.id", ondelete="CASCADE"), nullable=False
    )
    purchase_invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("purchase_invoices.id", ondelete="RESTRICT"), nullable=False
    )
    allocated_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)

    supplier_payment = relationship("SupplierPayment", back_populates="allocations")
    purchase_invoice = relationship(
        "PurchaseInvoice",
        back_populates="supplier_payment_allocations",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "supplier_payment_id",
            "purchase_invoice_id",
            name="supplier_payment_allocations_payment_invoice_key",
        ),
        Index(
            "supplier_payment_allocations_tenant_id_purchase_invoice_id_idx",
            "tenant_id",
            "purchase_invoice_id",
        ),
    )


class SupplierLedgerEntry(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_ledger_entries"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    entry_type: Mapped[SupplierLedgerEntryType] = str_enum_column(
        SupplierLedgerEntryType,
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

    tenant = relationship("Tenant", back_populates="supplier_ledger_entries")
    supplier = relationship("Supplier", back_populates="supplier_ledger_entries")

    __table_args__ = (
        Index(
            "supplier_ledger_entries_tenant_id_supplier_id_posted_at_idx",
            "tenant_id",
            "supplier_id",
            "posted_at",
        ),
        Index(
            "supplier_ledger_entries_tenant_id_source_type_source_id_idx",
            "tenant_id",
            "source_type",
            "source_id",
        ),
    )


class SupplierBalance(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "supplier_balances"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False
    )
    balance_amount: Mapped[Decimal] = mapped_column(
        Numeric(20, 4), nullable=False, default=Decimal("0"), server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    tenant = relationship("Tenant", back_populates="supplier_balances")
    supplier = relationship("Supplier", back_populates="supplier_balance")

    __table_args__ = (
        UniqueConstraint("tenant_id", "supplier_id", name="supplier_balances_tenant_supplier_key"),
    )
