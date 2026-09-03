"""add sales invoice line costs

Revision ID: k2a3b4c5d667
Revises: j1f2a3b4c556
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "k2a3b4c5d667"
down_revision: str | None = "j1f2a3b4c556"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_invoice_line_costs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sales_invoice_line_id", sa.Uuid(), nullable=False),
        sa.Column("stock_batch_id", sa.Uuid(), nullable=False),
        sa.Column("stock_movement_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit_cost_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 4), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["sales_invoice_line_id"],
            ["sales_invoice_lines.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["stock_batch_id"], ["stock_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stock_movement_id"], ["stock_movements.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "sales_invoice_line_costs_tenant_id_sales_invoice_line_id_idx",
        "sales_invoice_line_costs",
        ["tenant_id", "sales_invoice_line_id"],
    )
    op.create_index(
        "sales_invoice_line_costs_tenant_id_stock_batch_id_idx",
        "sales_invoice_line_costs",
        ["tenant_id", "stock_batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "sales_invoice_line_costs_tenant_id_stock_batch_id_idx",
        table_name="sales_invoice_line_costs",
    )
    op.drop_index(
        "sales_invoice_line_costs_tenant_id_sales_invoice_line_id_idx",
        table_name="sales_invoice_line_costs",
    )
    op.drop_table("sales_invoice_line_costs")
