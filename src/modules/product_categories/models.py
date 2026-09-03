import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin


class ProductCategory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_categories"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    parent_category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="product_categories")
    parent_category = relationship(
        "ProductCategory",
        remote_side="ProductCategory.id",
        back_populates="child_categories",
    )
    child_categories = relationship("ProductCategory", back_populates="parent_category")

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="product_categories_tenant_id_code_key"),
        Index(
            "product_categories_tenant_id_parent_category_id_idx",
            "tenant_id",
            "parent_category_id",
        ),
        Index("product_categories_tenant_id_name_idx", "tenant_id", "name"),
        Index("product_categories_tenant_id_is_active_idx", "tenant_id", "is_active"),
    )
