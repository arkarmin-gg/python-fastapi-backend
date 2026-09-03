"""Add sales invoice line source locations.

Revision ID: a8b9c0d1e223
Revises: z7d8e9f0a112
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8b9c0d1e223"
down_revision: str | Sequence[str] | None = "z7d8e9f0a112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sales_invoice_lines",
        sa.Column("source_location_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "sales_invoice_lines_source_location_id_fkey",
        "sales_invoice_lines",
        "locations",
        ["source_location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "sales_invoice_lines_tenant_id_source_location_id_idx",
        "sales_invoice_lines",
        ["tenant_id", "source_location_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "sales_invoice_lines_tenant_id_source_location_id_idx",
        table_name="sales_invoice_lines",
    )
    op.drop_constraint(
        "sales_invoice_lines_source_location_id_fkey",
        "sales_invoice_lines",
        type_="foreignkey",
    )
    op.drop_column("sales_invoice_lines", "source_location_id")
