"""add product units catalog

Revision ID: f0c1d2e3a445
Revises: e9b0c1d2f334
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0c1d2e3a445"
down_revision: str | None = "e9b0c1d2f334"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_units",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="product_units_product_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="product_units_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="product_units_unit_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="product_units_pkey"),
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


def downgrade() -> None:
    op.drop_index("product_units_tenant_id_unit_id_idx", table_name="product_units")
    op.drop_table("product_units")
