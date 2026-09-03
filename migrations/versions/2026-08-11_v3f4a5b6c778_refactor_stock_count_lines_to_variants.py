"""refactor stock count lines to variants

Revision ID: v3f4a5b6c778
Revises: u2e3f4a5b667
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "v3f4a5b6c778"
down_revision: str | Sequence[str] | None = "u2e3f4a5b667"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM stock_count_lines")

    op.add_column(
        "stock_count_lines",
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
    )
    op.alter_column("stock_count_lines", "product_id", nullable=True)
    op.create_foreign_key(
        "stock_count_lines_product_variant_id_fkey",
        "stock_count_lines",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "stock_count_lines_tenant_variant_batch_idx",
        "stock_count_lines",
        ["tenant_id", "product_variant_id", "stock_batch_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("stock_count_lines_tenant_variant_batch_idx", table_name="stock_count_lines")
    op.drop_constraint(
        "stock_count_lines_product_variant_id_fkey",
        "stock_count_lines",
        type_="foreignkey",
    )
    op.alter_column("stock_count_lines", "product_id", nullable=False)
    op.drop_column("stock_count_lines", "product_variant_id")
