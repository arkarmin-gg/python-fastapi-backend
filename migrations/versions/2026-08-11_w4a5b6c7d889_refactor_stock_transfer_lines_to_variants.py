"""refactor stock transfer lines to variants

Revision ID: w4a5b6c7d889
Revises: v3f4a5b6c778
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "w4a5b6c7d889"
down_revision: str | Sequence[str] | None = "v3f4a5b6c778"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM stock_transfer_lines")

    op.add_column(
        "stock_transfer_lines",
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
    )
    op.add_column(
        "stock_transfer_lines",
        sa.Column("variant_unit_id", sa.Uuid(), nullable=False),
    )
    op.alter_column("stock_transfer_lines", "product_id", nullable=True)
    op.alter_column("stock_transfer_lines", "unit_id", nullable=True)
    op.create_foreign_key(
        "stock_transfer_lines_product_variant_id_fkey",
        "stock_transfer_lines",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "stock_transfer_lines_variant_unit_id_fkey",
        "stock_transfer_lines",
        "variant_units",
        ["variant_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "stock_transfer_lines_tenant_id_product_variant_id_idx",
        "stock_transfer_lines",
        ["tenant_id", "product_variant_id"],
        unique=False,
    )
    op.create_index(
        "stock_transfer_lines_tenant_id_variant_unit_id_idx",
        "stock_transfer_lines",
        ["tenant_id", "variant_unit_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "stock_transfer_lines_tenant_id_variant_unit_id_idx",
        table_name="stock_transfer_lines",
    )
    op.drop_index(
        "stock_transfer_lines_tenant_id_product_variant_id_idx",
        table_name="stock_transfer_lines",
    )
    op.drop_constraint(
        "stock_transfer_lines_variant_unit_id_fkey",
        "stock_transfer_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_transfer_lines_product_variant_id_fkey",
        "stock_transfer_lines",
        type_="foreignkey",
    )
    op.alter_column("stock_transfer_lines", "unit_id", nullable=False)
    op.alter_column("stock_transfer_lines", "product_id", nullable=False)
    op.drop_column("stock_transfer_lines", "variant_unit_id")
    op.drop_column("stock_transfer_lines", "product_variant_id")
