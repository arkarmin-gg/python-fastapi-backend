"""Refactor purchase invoice lines to variants.

Revision ID: s0c1d2e3f445
Revises: r9b0c1d2e334
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "s0c1d2e3f445"
down_revision: str | Sequence[str] | None = "r9b0c1d2e334"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM purchase_landed_costs")
    op.execute("DELETE FROM purchase_invoice_lines")

    op.add_column(
        "purchase_invoice_lines",
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
    )
    op.add_column(
        "purchase_invoice_lines",
        sa.Column("variant_unit_id", sa.Uuid(), nullable=False),
    )
    op.alter_column("purchase_invoice_lines", "product_id", existing_type=sa.Uuid(), nullable=True)
    op.alter_column("purchase_invoice_lines", "unit_id", existing_type=sa.Uuid(), nullable=True)
    op.create_foreign_key(
        "purchase_invoice_lines_product_variant_id_fkey",
        "purchase_invoice_lines",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "purchase_invoice_lines_variant_unit_id_fkey",
        "purchase_invoice_lines",
        "variant_units",
        ["variant_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "purchase_invoice_lines_tenant_id_product_variant_id_idx",
        "purchase_invoice_lines",
        ["tenant_id", "product_variant_id"],
    )


def downgrade() -> None:
    op.execute("DELETE FROM purchase_landed_costs")
    op.execute("DELETE FROM purchase_invoice_lines")

    op.drop_index(
        "purchase_invoice_lines_tenant_id_product_variant_id_idx",
        table_name="purchase_invoice_lines",
    )
    op.drop_constraint(
        "purchase_invoice_lines_variant_unit_id_fkey",
        "purchase_invoice_lines",
        type_="foreignkey",
    )
    op.drop_constraint(
        "purchase_invoice_lines_product_variant_id_fkey",
        "purchase_invoice_lines",
        type_="foreignkey",
    )
    op.alter_column("purchase_invoice_lines", "unit_id", existing_type=sa.Uuid(), nullable=False)
    op.alter_column(
        "purchase_invoice_lines",
        "product_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.drop_column("purchase_invoice_lines", "variant_unit_id")
    op.drop_column("purchase_invoice_lines", "product_variant_id")
