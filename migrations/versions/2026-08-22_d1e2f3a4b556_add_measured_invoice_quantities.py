"""add measured invoice quantities

Revision ID: d1e2f3a4b556
Revises: c0d1e2f3a445
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d1e2f3a4b556"
down_revision: str | None = "c0d1e2f3a445"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "purchase_invoice_lines",
        sa.Column("measured_quantity", sa.Numeric(24, 8), nullable=True),
    )
    op.execute("UPDATE purchase_invoice_lines SET measured_quantity = quantity_base / quantity")
    op.alter_column("purchase_invoice_lines", "measured_quantity", nullable=False)

    op.add_column(
        "sales_invoice_lines",
        sa.Column("measured_quantity", sa.Numeric(24, 8), nullable=True),
    )
    op.execute("UPDATE sales_invoice_lines SET measured_quantity = quantity_base / quantity")
    op.alter_column("sales_invoice_lines", "measured_quantity", nullable=False)


def downgrade() -> None:
    op.drop_column("sales_invoice_lines", "measured_quantity")
    op.drop_column("purchase_invoice_lines", "measured_quantity")
