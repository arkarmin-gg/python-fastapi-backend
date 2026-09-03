"""add catalog items and product variants

Revision ID: p7f8a9b0c112
Revises: o6e7f8a9b001
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "p7f8a9b0c112"
down_revision: str | None = "o6e7f8a9b001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


catalog_item_kind = sa.Enum(
    "stocked",
    "service",
    "composite",
    native_enum=False,
    length=50,
)
pos_tile_shape = sa.Enum(
    "square",
    "circle",
    "scallop",
    "hexagon",
    native_enum=False,
    length=50,
)


def upgrade() -> None:
    op.create_table(
        "catalog_items",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("local_name", sa.String(length=240), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("item_kind", catalog_item_kind, server_default="stocked", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["product_categories.id"],
            name="catalog_items_category_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="catalog_items_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="catalog_items_pkey"),
    )
    op.create_index("catalog_items_tenant_id_name_idx", "catalog_items", ["tenant_id", "name"])
    op.create_index(
        "catalog_items_tenant_id_category_id_idx", "catalog_items", ["tenant_id", "category_id"]
    )
    op.create_index(
        "catalog_items_tenant_id_item_kind_idx", "catalog_items", ["tenant_id", "item_kind"]
    )
    op.create_index(
        "catalog_items_tenant_id_is_active_idx", "catalog_items", ["tenant_id", "is_active"]
    )

    op.create_table(
        "product_variants",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("local_name", sa.String(length=160), nullable=True),
        sa.Column("base_unit_id", sa.Uuid(), nullable=False),
        sa.Column("default_sale_price", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("default_purchase_cost", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("track_inventory", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("track_batches", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("track_expiry", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["base_unit_id"],
            ["units.id"],
            name="product_variants_base_unit_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["catalog_items.id"],
            name="product_variants_catalog_item_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="product_variants_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="product_variants_pkey"),
        sa.UniqueConstraint("tenant_id", "sku", name="product_variants_tenant_id_sku_key"),
    )
    op.create_index(
        "product_variants_tenant_id_catalog_item_id_idx",
        "product_variants",
        ["tenant_id", "catalog_item_id"],
    )
    op.create_index(
        "product_variants_tenant_id_base_unit_id_idx",
        "product_variants",
        ["tenant_id", "base_unit_id"],
    )
    op.create_index(
        "product_variants_tenant_id_is_active_idx",
        "product_variants",
        ["tenant_id", "is_active"],
    )

    op.create_table(
        "variant_units",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("is_base_unit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_purchase_unit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_sales_unit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("allow_decimal_quantity", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "rounding_precision",
            sa.Numeric(precision=24, scale=8),
            server_default="0.000001",
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("conversion_to_base > 0", name="variant_units_conversion_positive"),
        sa.CheckConstraint("rounding_precision > 0", name="variant_units_rounding_positive"),
        sa.ForeignKeyConstraint(
            ["product_variant_id"],
            ["product_variants.id"],
            name="variant_units_product_variant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="variant_units_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="variant_units_unit_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="variant_units_pkey"),
    )
    op.create_index(
        "variant_units_tenant_id_product_variant_id_idx",
        "variant_units",
        ["tenant_id", "product_variant_id"],
    )
    op.create_index(
        "variant_units_tenant_id_unit_id_idx",
        "variant_units",
        ["tenant_id", "unit_id"],
    )
    op.create_index(
        "variant_units_active_variant_unit_key",
        "variant_units",
        ["tenant_id", "product_variant_id", "unit_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "variant_units_active_base_key",
        "variant_units",
        ["tenant_id", "product_variant_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND is_base_unit"),
    )

    op.create_table(
        "variant_barcodes",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("variant_unit_id", sa.Uuid(), nullable=True),
        sa.Column("barcode", sa.String(length=120), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["product_variant_id"],
            ["product_variants.id"],
            name="variant_barcodes_product_variant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="variant_barcodes_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["variant_unit_id"],
            ["variant_units.id"],
            name="variant_barcodes_variant_unit_id_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="variant_barcodes_pkey"),
    )
    op.create_index(
        "variant_barcodes_tenant_id_product_variant_id_idx",
        "variant_barcodes",
        ["tenant_id", "product_variant_id"],
    )
    op.create_index(
        "variant_barcodes_active_barcode_key",
        "variant_barcodes",
        ["tenant_id", "barcode"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "variant_barcodes_active_primary_key",
        "variant_barcodes",
        ["tenant_id", "product_variant_id"],
        unique=True,
        postgresql_where=sa.text("is_active AND is_primary"),
    )

    op.create_table(
        "variant_pos_profiles",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("color", sa.String(length=20), nullable=True),
        sa.Column("shape", pos_tile_shape, server_default="square", nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_visible", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["product_variant_id"],
            ["product_variants.id"],
            name="variant_pos_profiles_product_variant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="variant_pos_profiles_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="variant_pos_profiles_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_variant_id",
            name="variant_pos_profiles_tenant_id_product_variant_id_key",
        ),
    )
    op.create_index(
        "variant_pos_profiles_tenant_id_sort_order_idx",
        "variant_pos_profiles",
        ["tenant_id", "sort_order"],
    )

    op.create_table(
        "variant_location_settings",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("is_available", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("low_stock_quantity_base", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("preferred_supplier_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "low_stock_quantity_base IS NULL OR low_stock_quantity_base >= 0",
            name="variant_location_settings_low_stock_non_negative",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name="variant_location_settings_location_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["preferred_supplier_id"],
            ["suppliers.id"],
            name="variant_location_settings_preferred_supplier_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_variant_id"],
            ["product_variants.id"],
            name="variant_location_settings_product_variant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="variant_location_settings_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="variant_location_settings_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_variant_id",
            "location_id",
            name="variant_location_settings_variant_location_key",
        ),
    )
    op.create_index(
        "variant_location_settings_tenant_id_location_id_idx",
        "variant_location_settings",
        ["tenant_id", "location_id"],
    )

    op.create_table(
        "catalog_item_option_groups",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("catalog_item_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["catalog_item_id"],
            ["catalog_items.id"],
            name="catalog_item_option_groups_catalog_item_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="catalog_item_option_groups_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="catalog_item_option_groups_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "catalog_item_id",
            "name",
            name="catalog_item_option_groups_item_name_key",
        ),
    )

    op.create_table(
        "catalog_item_option_values",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("option_group_id", sa.Uuid(), nullable=False),
        sa.Column("value", sa.String(length=120), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["option_group_id"],
            ["catalog_item_option_groups.id"],
            name="catalog_item_option_values_option_group_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="catalog_item_option_values_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="catalog_item_option_values_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "option_group_id",
            "value",
            name="catalog_item_option_values_group_value_key",
        ),
    )

    op.create_table(
        "product_variant_option_values",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("option_value_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["option_value_id"],
            ["catalog_item_option_values.id"],
            name="product_variant_option_values_option_value_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_variant_id"],
            ["product_variants.id"],
            name="product_variant_option_values_product_variant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="product_variant_option_values_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="product_variant_option_values_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_variant_id",
            "option_value_id",
            name="product_variant_option_values_variant_value_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("product_variant_option_values")
    op.drop_table("catalog_item_option_values")
    op.drop_table("catalog_item_option_groups")
    op.drop_index(
        "variant_location_settings_tenant_id_location_id_idx",
        table_name="variant_location_settings",
    )
    op.drop_table("variant_location_settings")
    op.drop_index(
        "variant_pos_profiles_tenant_id_sort_order_idx",
        table_name="variant_pos_profiles",
    )
    op.drop_table("variant_pos_profiles")
    op.drop_index("variant_barcodes_active_primary_key", table_name="variant_barcodes")
    op.drop_index("variant_barcodes_active_barcode_key", table_name="variant_barcodes")
    op.drop_index(
        "variant_barcodes_tenant_id_product_variant_id_idx",
        table_name="variant_barcodes",
    )
    op.drop_table("variant_barcodes")
    op.drop_index("variant_units_active_base_key", table_name="variant_units")
    op.drop_index("variant_units_active_variant_unit_key", table_name="variant_units")
    op.drop_index("variant_units_tenant_id_unit_id_idx", table_name="variant_units")
    op.drop_index("variant_units_tenant_id_product_variant_id_idx", table_name="variant_units")
    op.drop_table("variant_units")
    op.drop_index("product_variants_tenant_id_is_active_idx", table_name="product_variants")
    op.drop_index("product_variants_tenant_id_base_unit_id_idx", table_name="product_variants")
    op.drop_index("product_variants_tenant_id_catalog_item_id_idx", table_name="product_variants")
    op.drop_table("product_variants")
    op.drop_index("catalog_items_tenant_id_is_active_idx", table_name="catalog_items")
    op.drop_index("catalog_items_tenant_id_item_kind_idx", table_name="catalog_items")
    op.drop_index("catalog_items_tenant_id_category_id_idx", table_name="catalog_items")
    op.drop_index("catalog_items_tenant_id_name_idx", table_name="catalog_items")
    op.drop_table("catalog_items")
