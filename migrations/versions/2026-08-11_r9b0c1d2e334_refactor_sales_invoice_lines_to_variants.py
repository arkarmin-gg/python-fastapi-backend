"""Refactor sales invoice lines to variants.

Revision ID: r9b0c1d2e334
Revises: q8a9b0c1d223
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "r9b0c1d2e334"
down_revision: str | Sequence[str] | None = "q8a9b0c1d223"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM sales_invoice_line_costs")
    op.execute("DELETE FROM sales_invoice_lines")

    op.add_column("product_variants", sa.Column("legacy_product_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "product_variants_legacy_product_id_fkey",
        "product_variants",
        "products",
        ["legacy_product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "product_variants_tenant_id_legacy_product_id_idx",
        "product_variants",
        ["tenant_id", "legacy_product_id"],
    )

    op.add_column(
        "sales_invoice_lines",
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
    )
    op.add_column(
        "sales_invoice_lines",
        sa.Column("variant_unit_id", sa.Uuid(), nullable=False),
    )
    op.alter_column("sales_invoice_lines", "product_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("sales_invoice_lines", "unit_id", existing_type=sa.Uuid(), nullable=True)
    op.create_foreign_key(
        "sales_invoice_lines_product_variant_id_fkey",
        "sales_invoice_lines",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "sales_invoice_lines_variant_unit_id_fkey",
        "sales_invoice_lines",
        "variant_units",
        ["variant_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "sales_invoice_lines_tenant_id_product_variant_id_idx",
        "sales_invoice_lines",
        ["tenant_id", "product_variant_id"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM sales_invoice_line_costs")
    op.execute("DELETE FROM sales_invoice_lines")

    op.drop_index(
        "sales_invoice_lines_tenant_id_product_variant_id_idx",
        table_name="sales_invoice_lines",
    )
    op.drop_constraint(
        "sales_invoice_lines_variant_unit_id_fkey",
        "sales_invoice_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "sales_invoice_lines_product_variant_id_fkey",
        "sales_invoice_lines",
        type_="foreignkey",
    )
    op.alter_column("sales_invoice_lines", "unit_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column("sales_invoice_lines", "product_id", existing_type=sa.Uuid(), nullable=False)
    op.drop_column("sales_invoice_lines", "variant_unit_id")
    op.drop_column("sales_invoice_lines", "product_variant_id")

    op.drop_index(
        "product_variants_tenant_id_legacy_product_id_idx",
        table_name="product_variants",
    )
    op.drop_constraint(
        "product_variants_legacy_product_id_fkey",
        "product_variants",
        type_="foreignkey",
    )
    op.drop_column("product_variants", "legacy_product_id")
