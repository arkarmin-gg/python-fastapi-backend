import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, UUIDPrimaryKeyMixin


class PriceLevel(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "price_levels"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="price_levels")
    customers = relationship("Customer", back_populates="price_level")
    price_rules = relationship("PriceRule", back_populates="price_level")
    sales_invoices = relationship("SalesInvoice", back_populates="price_level")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="price_levels_tenant_id_code_key"),
        Index("price_levels_tenant_id_name_idx", "tenant_id", "name"),
        Index("price_levels_tenant_id_is_default_idx", "tenant_id", "is_default"),
        Index("price_levels_tenant_id_is_active_idx", "tenant_id", "is_active"),
    )
