import uuid
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.ext.associationproxy import association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.foundation_enums import CatalogItemKind, PosTileShape
from src.models import Base, TimestampMixin, UUIDPrimaryKeyMixin, str_enum_column


class CatalogItem(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "catalog_items"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(240), nullable=False)
    local_name: Mapped[str | None] = mapped_column(String(240), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("product_categories.id", ondelete="SET NULL"), nullable=True
    )
    item_kind: Mapped[CatalogItemKind] = str_enum_column(
        CatalogItemKind,
        nullable=False,
        default=CatalogItemKind.STOCKED,
        server_default=CatalogItemKind.STOCKED.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    image_key: Mapped[str | None] = mapped_column(String(500), nullable=True)

    tenant = relationship("Tenant", back_populates="catalog_items")
    category = relationship("ProductCategory")
    variants = relationship(
        "ProductVariant",
        back_populates="catalog_item",
        cascade="all, delete-orphan",
    )
    option_groups = relationship(
        "CatalogItemOptionGroup",
        back_populates="catalog_item",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="catalog_items_tenant_id_code_key"),
        Index("catalog_items_tenant_id_code_idx", "tenant_id", "code"),
        Index("catalog_items_tenant_id_name_idx", "tenant_id", "name"),
        Index("catalog_items_tenant_id_category_id_idx", "tenant_id", "category_id"),
        Index("catalog_items_tenant_id_item_kind_idx", "tenant_id", "item_kind"),
        Index("catalog_items_tenant_id_is_active_idx", "tenant_id", "is_active"),
    )


class ProductVariant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "product_variants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    local_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    base_unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    default_sale_price: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    default_purchase_cost: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    track_inventory: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    track_batches: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    track_expiry: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="product_variants")
    catalog_item = relationship("CatalogItem", back_populates="variants")
    base_unit = relationship("Unit")
    variant_units = relationship(
        "VariantUnit",
        back_populates="product_variant",
        cascade="all, delete-orphan",
    )
    barcodes = relationship(
        "VariantBarcode",
        back_populates="product_variant",
        cascade="all, delete-orphan",
    )
    pos_profile = relationship(
        "VariantPosProfile",
        back_populates="product_variant",
        cascade="all, delete-orphan",
        uselist=False,
    )
    location_settings = relationship(
        "VariantLocationSetting",
        back_populates="product_variant",
        cascade="all, delete-orphan",
    )
    price_rules = relationship("PriceRule", back_populates="product_variant")
    purchase_invoice_lines = relationship("PurchaseInvoiceLine", back_populates="product_variant")
    sales_invoice_lines = relationship("SalesInvoiceLine", back_populates="product_variant")
    stock_adjustment_lines = relationship("StockAdjustmentLine", back_populates="product_variant")
    stock_count_lines = relationship("StockCountLine", back_populates="product_variant")
    stock_transfer_lines = relationship("StockTransferLine", back_populates="product_variant")
    repack_order_inputs = relationship("RepackOrderInput", back_populates="product_variant")
    repack_order_outputs = relationship("RepackOrderOutput", back_populates="product_variant")
    stock_batches = relationship("StockBatch", back_populates="product_variant")
    stock_movements = relationship("StockMovement", back_populates="product_variant")
    stock_balances = relationship("StockBalance", back_populates="product_variant")
    option_values = relationship(
        "ProductVariantOptionValue",
        back_populates="product_variant",
        cascade="all, delete-orphan",
    )
    base_unit_code = association_proxy("base_unit", "code")
    base_unit_name = association_proxy("base_unit", "name_en")

    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="product_variants_tenant_id_sku_key"),
        Index("product_variants_tenant_id_catalog_item_id_idx", "tenant_id", "catalog_item_id"),
        Index("product_variants_tenant_id_base_unit_id_idx", "tenant_id", "base_unit_id"),
        Index("product_variants_tenant_id_is_active_idx", "tenant_id", "is_active"),
    )


class VariantUnit(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "variant_units"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("units.id", ondelete="RESTRICT"), nullable=False
    )
    is_base_unit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_purchase_unit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_sales_unit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    conversion_to_base: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False)
    allow_decimal_quantity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    rounding_precision: Mapped[Decimal] = mapped_column(
        Numeric(24, 8), nullable=False, default=Decimal("0.000001"), server_default="0.000001"
    )
    requires_measured_quantity: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="variant_units")
    product_variant = relationship("ProductVariant", back_populates="variant_units")
    unit = relationship("Unit")
    barcodes = relationship("VariantBarcode", back_populates="variant_unit")
    purchase_invoice_lines = relationship("PurchaseInvoiceLine", back_populates="variant_unit")
    sales_invoice_lines = relationship("SalesInvoiceLine", back_populates="variant_unit")
    stock_adjustment_lines = relationship("StockAdjustmentLine", back_populates="variant_unit")
    stock_transfer_lines = relationship("StockTransferLine", back_populates="variant_unit")
    repack_order_inputs = relationship("RepackOrderInput", back_populates="variant_unit")
    repack_order_outputs = relationship("RepackOrderOutput", back_populates="variant_unit")

    __table_args__ = (
        CheckConstraint("conversion_to_base > 0", name="variant_units_conversion_positive"),
        CheckConstraint("rounding_precision > 0", name="variant_units_rounding_positive"),
        Index("variant_units_tenant_id_product_variant_id_idx", "tenant_id", "product_variant_id"),
        Index("variant_units_tenant_id_unit_id_idx", "tenant_id", "unit_id"),
        Index(
            "variant_units_active_variant_unit_key",
            "tenant_id",
            "product_variant_id",
            "unit_id",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index(
            "variant_units_active_base_key",
            "tenant_id",
            "product_variant_id",
            unique=True,
            postgresql_where=text("is_active AND is_base_unit"),
        ),
    )


class VariantBarcode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "variant_barcodes"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    variant_unit_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("variant_units.id", ondelete="SET NULL"), nullable=True
    )
    barcode: Mapped[str] = mapped_column(String(120), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="variant_barcodes")
    product_variant = relationship("ProductVariant", back_populates="barcodes")
    variant_unit = relationship("VariantUnit", back_populates="barcodes")

    __table_args__ = (
        Index(
            "variant_barcodes_tenant_id_product_variant_id_idx",
            "tenant_id",
            "product_variant_id",
        ),
        Index(
            "variant_barcodes_active_barcode_key",
            "tenant_id",
            "barcode",
            unique=True,
            postgresql_where=text("is_active"),
        ),
        Index(
            "variant_barcodes_active_primary_key",
            "tenant_id",
            "product_variant_id",
            unique=True,
            postgresql_where=text("is_active AND is_primary"),
        ),
    )


class VariantPosProfile(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "variant_pos_profiles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str | None] = mapped_column(String(80), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    shape: Mapped[PosTileShape] = str_enum_column(
        PosTileShape,
        nullable=False,
        default=PosTileShape.SQUARE,
        server_default=PosTileShape.SQUARE.value,
    )
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    is_visible: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    tenant = relationship("Tenant", back_populates="variant_pos_profiles")
    product_variant = relationship("ProductVariant", back_populates="pos_profile")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_variant_id",
            name="variant_pos_profiles_tenant_id_product_variant_id_key",
        ),
        Index("variant_pos_profiles_tenant_id_sort_order_idx", "tenant_id", "sort_order"),
    )


class VariantLocationSetting(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "variant_location_settings"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    location_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("locations.id", ondelete="CASCADE"), nullable=False
    )
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    low_stock_quantity_base: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    preferred_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("suppliers.id", ondelete="SET NULL"), nullable=True
    )

    tenant = relationship("Tenant", back_populates="variant_location_settings")
    product_variant = relationship("ProductVariant", back_populates="location_settings")
    location = relationship("Location", back_populates="variant_location_settings")
    preferred_supplier = relationship("Supplier")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_variant_id",
            "location_id",
            name="variant_location_settings_variant_location_key",
        ),
        CheckConstraint(
            "low_stock_quantity_base IS NULL OR low_stock_quantity_base >= 0",
            name="variant_location_settings_low_stock_non_negative",
        ),
        Index(
            "variant_location_settings_tenant_id_location_id_idx",
            "tenant_id",
            "location_id",
        ),
    )


class CatalogItemOptionGroup(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "catalog_item_option_groups"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    catalog_item_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalog_items.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    catalog_item = relationship("CatalogItem", back_populates="option_groups")
    values = relationship(
        "CatalogItemOptionValue",
        back_populates="option_group",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "catalog_item_id",
            "name",
            name="catalog_item_option_groups_item_name_key",
        ),
    )


class CatalogItemOptionValue(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "catalog_item_option_values"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    option_group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalog_item_option_groups.id", ondelete="CASCADE"), nullable=False
    )
    value: Mapped[str] = mapped_column(String(120), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    option_group = relationship("CatalogItemOptionGroup", back_populates="values")
    variant_links = relationship(
        "ProductVariantOptionValue",
        back_populates="option_value",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "option_group_id",
            "value",
            name="catalog_item_option_values_group_value_key",
        ),
    )


class ProductVariantOptionValue(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "product_variant_option_values"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_variant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False
    )
    option_value_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("catalog_item_option_values.id", ondelete="CASCADE"), nullable=False
    )

    product_variant = relationship("ProductVariant", back_populates="option_values")
    option_value = relationship("CatalogItemOptionValue", back_populates="variant_links")

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_variant_id",
            "option_value_id",
            name="product_variant_option_values_variant_value_key",
        ),
    )
