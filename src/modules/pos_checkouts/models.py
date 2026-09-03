import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import PaymentMethod
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class PosCheckout(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One committed customer checkout and its immutable tender snapshot."""

    __tablename__ = "pos_checkouts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    sales_invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("sales_invoices.id", ondelete="RESTRICT"), nullable=False
    )
    customer_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("customer_payments.id", ondelete="RESTRICT"), nullable=True
    )
    payment_method: Mapped[PaymentMethod | None] = str_enum_column(
        PaymentMethod,
        nullable=True,
    )
    paid_now_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    cash_tendered_amount: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    change_due_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    charged_to_account_amount: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    customer_balance_after: Mapped[Decimal] = mapped_column(Numeric(20, 4), nullable=False)
    available_credit_after: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    tenant = relationship("Tenant", back_populates="pos_checkouts")
    sales_invoice = relationship("SalesInvoice", back_populates="pos_checkout")
    customer_payment = relationship("CustomerPayment", back_populates="pos_checkout")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="pos_checkouts_tenant_id_idempotency_key_key",
        ),
        UniqueConstraint(
            "tenant_id",
            "sales_invoice_id",
            name="pos_checkouts_tenant_id_sales_invoice_id_key",
        ),
        UniqueConstraint(
            "tenant_id",
            "customer_payment_id",
            name="pos_checkouts_tenant_id_customer_payment_id_key",
        ),
        Index(
            "pos_checkouts_tenant_id_created_at_idx",
            "tenant_id",
            "created_at",
        ),
    )
