import uuid

from sqlalchemy import ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import PartyStatus, SupplierType
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    supplier_type: Mapped[SupplierType] = str_enum_column(
        SupplierType,
        nullable=False,
        default=SupplierType.LOCAL,
        server_default=SupplierType.LOCAL.value,
    )
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[PartyStatus] = str_enum_column(
        PartyStatus,
        nullable=False,
        default=PartyStatus.ACTIVE,
        server_default=PartyStatus.ACTIVE.value,
    )

    tenant = relationship("Tenant", back_populates="suppliers")
    purchase_invoices = relationship("PurchaseInvoice", back_populates="supplier")
    supplier_payments = relationship("SupplierPayment", back_populates="supplier")
    supplier_ledger_entries = relationship("SupplierLedgerEntry", back_populates="supplier")
    supplier_balance = relationship("SupplierBalance", back_populates="supplier", uselist=False)
    stock_batches = relationship("StockBatch", back_populates="supplier")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="suppliers_tenant_id_code_key"),
        Index("suppliers_tenant_id_name_idx", "tenant_id", "name"),
    )
