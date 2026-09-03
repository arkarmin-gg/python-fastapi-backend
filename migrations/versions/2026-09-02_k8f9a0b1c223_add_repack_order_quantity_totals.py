"""add repack order quantity totals

Revision ID: k8f9a0b1c223
Revises: j7e8f9a0b112
Create Date: 2026-09-02 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "k8f9a0b1c223"
down_revision: str | None = "j7e8f9a0b112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repack_orders",
        sa.Column(
            "total_input_quantity_base",
            sa.Numeric(24, 8),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "repack_orders",
        sa.Column(
            "total_output_quantity_base",
            sa.Numeric(24, 8),
            server_default="0",
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE repack_orders
        SET total_input_quantity_base = COALESCE(
            (
                SELECT sum(quantity_base)
                FROM repack_order_inputs
                WHERE repack_order_inputs.repack_order_id = repack_orders.id
            ),
            0
        )
        """
    )
    op.execute(
        """
        UPDATE repack_orders
        SET total_output_quantity_base = COALESCE(
            (
                SELECT sum(quantity_base)
                FROM repack_order_outputs
                WHERE repack_order_outputs.repack_order_id = repack_orders.id
            ),
            0
        )
        """
    )


def downgrade() -> None:
    op.drop_column("repack_orders", "total_output_quantity_base")
    op.drop_column("repack_orders", "total_input_quantity_base")
