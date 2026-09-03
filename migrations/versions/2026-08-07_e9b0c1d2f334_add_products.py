"""add products catalog

Revision ID: e9b0c1d2f334
Revises: d8a9b0c1e223
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e9b0c1d2f334"
down_revision: str | None = "d8a9b0c1e223"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sku", sa.String(length=80), nullable=False),
        sa.Column("barcode", sa.String(length=120), nullable=True),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column("local_name", sa.String(length=240), nullable=True),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("base_unit_id", sa.Uuid(), nullable=False),
        sa.Column(
            "product_type",
            sa.Enum(
                "standard",
                "bulk",
                "packaged",
                "alcohol",
                "service",
                native_enum=False,
                length=50,
            ),
            server_default="standard",
            nullable=False,
        ),
        sa.Column("parent_product_id", sa.Uuid(), nullable=True),
        sa.Column("track_inventory", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("track_batches", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("track_expiry", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("reorder_level_base", sa.Numeric(precision=24, scale=8), nullable=True),
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
            name="products_base_unit_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["product_categories.id"],
            name="products_category_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_product_id"],
            ["products.id"],
            name="products_parent_product_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="products_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="products_pkey"),
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


def downgrade() -> None:
    op.drop_index("products_tenant_id_parent_product_id_idx", table_name="products")
    op.drop_index("products_tenant_id_category_id_idx", table_name="products")
    op.drop_index("products_tenant_id_name_idx", table_name="products")
    op.drop_index("products_tenant_id_barcode_idx", table_name="products")
    op.drop_table("products")
