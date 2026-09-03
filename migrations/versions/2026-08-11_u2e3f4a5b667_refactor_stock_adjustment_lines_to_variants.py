"""refactor stock adjustment lines to variants

Revision ID: u2e3f4a5b667
Revises: t1d2e3f4a556
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "u2e3f4a5b667"
down_revision: str | Sequence[str] | None = "t1d2e3f4a556"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM stock_adjustment_lines")

    op.add_column(
        "stock_adjustment_lines",
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
    )
    op.add_column(
        "stock_adjustment_lines",
        sa.Column("variant_unit_id", sa.Uuid(), nullable=False),
    )
    op.alter_column("stock_adjustment_lines", "product_id", nullable=True)
    op.alter_column("stock_adjustment_lines", "unit_id", nullable=True)
    op.create_foreign_key(
        "stock_adjustment_lines_product_variant_id_fkey",
        "stock_adjustment_lines",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "stock_adjustment_lines_variant_unit_id_fkey",
        "stock_adjustment_lines",
        "variant_units",
        ["variant_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "stock_adjustment_lines_tenant_id_product_variant_id_idx",
        "stock_adjustment_lines",
        ["tenant_id", "product_variant_id"],
        unique=False,
    )
    op.create_index(
        "stock_adjustment_lines_tenant_id_variant_unit_id_idx",
        "stock_adjustment_lines",
        ["tenant_id", "variant_unit_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "stock_adjustment_lines_tenant_id_variant_unit_id_idx",
        table_name="stock_adjustment_lines",
    )
    op.drop_index(
        "stock_adjustment_lines_tenant_id_product_variant_id_idx",
        table_name="stock_adjustment_lines",
    )
    op.drop_constraint(
        "stock_adjustment_lines_variant_unit_id_fkey",
        "stock_adjustment_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_adjustment_lines_product_variant_id_fkey",
        "stock_adjustment_lines",
        type_="foreignkey",
    )
    op.alter_column("stock_adjustment_lines", "unit_id", nullable=False)
    op.alter_column("stock_adjustment_lines", "product_id", nullable=False)
    op.drop_column("stock_adjustment_lines", "variant_unit_id")
    op.drop_column("stock_adjustment_lines", "product_variant_id")
