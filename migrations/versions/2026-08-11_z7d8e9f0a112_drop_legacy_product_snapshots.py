"""drop legacy product snapshots

Revision ID: z7d8e9f0a112
Revises: y6c7d8e9f001
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "z7d8e9f0a112"
down_revision: str | Sequence[str] | None = "y6c7d8e9f001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Development-only destructive cleanup: old operational rows may not have
    # variant identities, so clear them before enforcing variant-only columns.
    op.execute("DELETE FROM sales_invoice_line_costs")
    op.execute("DELETE FROM stock_movements")
    op.execute("DELETE FROM stock_balances")
    op.execute("DELETE FROM repack_order_inputs")
    op.execute("DELETE FROM repack_order_outputs")
    op.execute("DELETE FROM stock_transfer_lines")
    op.execute("DELETE FROM stock_count_lines")
    op.execute("DELETE FROM stock_adjustment_lines")
    op.execute("DELETE FROM purchase_landed_costs")
    op.execute("DELETE FROM purchase_invoice_lines")
    op.execute("DELETE FROM sales_invoice_lines")
    op.execute("DELETE FROM stock_batches")
    op.execute(
        "DELETE FROM price_rules WHERE product_variant_id IS NULL OR variant_unit_id IS NULL"
    )

    op.drop_index("price_rules_scope_effective_from_idx", table_name="price_rules")
    op.drop_index(
        "purchase_invoice_lines_tenant_id_product_id_idx", table_name="purchase_invoice_lines"
    )
    op.drop_index("sales_invoice_lines_tenant_id_product_id_idx", table_name="sales_invoice_lines")
    op.drop_index(
        "stock_adjustment_lines_tenant_id_product_id_idx",
        table_name="stock_adjustment_lines",
    )
    op.drop_index("stock_count_lines_tenant_product_batch_idx", table_name="stock_count_lines")
    op.drop_index(
        "stock_batches_tenant_id_product_id_received_at_idx",
        table_name="stock_batches",
    )
    op.drop_index(
        "stock_batches_tenant_id_product_id_expiry_date_idx",
        table_name="stock_batches",
    )
    op.drop_index(
        "stock_movements_tenant_product_location_posted_idx",
        table_name="stock_movements",
    )
    op.drop_index(
        "stock_balances_tenant_id_product_id_location_id_idx",
        table_name="stock_balances",
    )
    op.drop_index(
        "product_variants_tenant_id_legacy_product_id_idx",
        table_name="product_variants",
    )

    op.drop_constraint("price_rules_product_id_fkey", "price_rules", type_="foreignkey")
    op.drop_constraint("price_rules_unit_id_fkey", "price_rules", type_="foreignkey")
    op.drop_constraint(
        "purchase_invoice_lines_product_id_fkey",
        "purchase_invoice_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "purchase_invoice_lines_unit_id_fkey",
        "purchase_invoice_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "sales_invoice_lines_product_id_fkey",
        "sales_invoice_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "sales_invoice_lines_unit_id_fkey",
        "sales_invoice_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_adjustment_lines_product_id_fkey",
        "stock_adjustment_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_adjustment_lines_unit_id_fkey",
        "stock_adjustment_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_count_lines_product_id_fkey",
        "stock_count_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_transfer_lines_product_id_fkey",
        "stock_transfer_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_transfer_lines_unit_id_fkey",
        "stock_transfer_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "repack_order_inputs_product_id_fkey",
        "repack_order_inputs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "repack_order_inputs_unit_id_fkey",
        "repack_order_inputs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "repack_order_outputs_product_id_fkey",
        "repack_order_outputs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "repack_order_outputs_unit_id_fkey",
        "repack_order_outputs",
        type_="foreignkey",
    )
    op.drop_constraint("stock_batches_product_id_fkey", "stock_batches", type_="foreignkey")
    op.drop_constraint("stock_movements_product_id_fkey", "stock_movements", type_="foreignkey")
    op.drop_constraint("stock_balances_product_id_fkey", "stock_balances", type_="foreignkey")
    op.drop_constraint(
        "stock_balances_tenant_product_location_batch_key",
        "stock_balances",
        type_="unique",
    )
    op.drop_constraint(
        "product_variants_legacy_product_id_fkey",
        "product_variants",
        type_="foreignkey",
    )

    for table_name in (
        "price_rules",
        "purchase_invoice_lines",
        "sales_invoice_lines",
        "stock_adjustment_lines",
        "stock_transfer_lines",
        "repack_order_inputs",
        "repack_order_outputs",
    ):
        op.drop_column(table_name, "unit_id")
        op.drop_column(table_name, "product_id")

    op.drop_column("stock_count_lines", "product_id")
    op.drop_column("stock_batches", "product_id")
    op.drop_column("stock_movements", "product_id")
    op.drop_column("stock_balances", "product_id")
    op.drop_column("product_variants", "legacy_product_id")

    op.alter_column("price_rules", "product_variant_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("price_rules", "variant_unit_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("stock_batches", "product_variant_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column(
        "stock_movements", "product_variant_id", existing_type=sa.Uuid(), nullable=False
    )
    op.alter_column("stock_balances", "product_variant_id", existing_type=sa.Uuid(), nullable=False)

    op.drop_index("product_units_tenant_id_unit_id_idx", table_name="product_units")
    op.drop_table("product_units")
    op.drop_index("products_tenant_id_parent_product_id_idx", table_name="products")
    op.drop_index("products_tenant_id_category_id_idx", table_name="products")
    op.drop_index("products_tenant_id_name_idx", table_name="products")
    op.drop_index("products_tenant_id_barcode_idx", table_name="products")
    op.drop_table("products")


def downgrade() -> None:
    op.create_table(
        "products",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("barcode", sa.String(length=120), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("local_name", sa.String(length=240), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("base_unit_id", sa.Uuid(), nullable=False),
        sa.Column("product_type", sa.String(length=50), server_default="standard", nullable=False),
        sa.Column("parent_product_id", sa.Uuid(), nullable=True),
        sa.Column("track_inventory", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("track_batches", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("track_expiry", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reorder_level_base", sa.Numeric(24, 8), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["base_unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["category_id"], ["product_categories.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_product_id"], ["products.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "sku", name="products_tenant_id_sku_key"),
    )
    op.create_index("products_tenant_id_barcode_idx", "products", ["tenant_id", "barcode"])
    op.create_index("products_tenant_id_name_idx", "products", ["tenant_id", "name"])
    op.create_index("products_tenant_id_category_id_idx", "products", ["tenant_id", "category_id"])
    op.create_index(
        "products_tenant_id_parent_product_id_idx",
        "products",
        ["tenant_id", "parent_product_id"],
    )
    op.create_table(
        "product_units",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("is_base_unit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_purchase_unit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_sales_unit", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("allow_decimal_quantity", sa.Boolean(), server_default="true", nullable=False),
        sa.Column(
            "rounding_precision", sa.Numeric(24, 8), server_default="0.000001", nullable=False
        ),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "unit_id",
            name="product_units_tenant_id_product_id_unit_id_key",
        ),
    )
    op.create_index(
        "product_units_tenant_id_unit_id_idx", "product_units", ["tenant_id", "unit_id"]
    )
