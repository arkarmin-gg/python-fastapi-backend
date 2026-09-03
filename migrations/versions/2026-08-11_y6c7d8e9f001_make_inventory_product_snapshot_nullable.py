"""make inventory product snapshot nullable

Revision ID: y6c7d8e9f001
Revises: x5b6c7d8e990
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "y6c7d8e9f001"
down_revision: str | Sequence[str] | None = "x5b6c7d8e990"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("stock_batches", "product_id", nullable=True)
    op.alter_column("stock_movements", "product_id", nullable=True)
    op.alter_column("stock_balances", "product_id", nullable=True)
    op.create_unique_constraint(
        "stock_balances_tenant_variant_location_batch_key",
        "stock_balances",
        ["tenant_id", "product_variant_id", "location_id", "stock_batch_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "stock_balances_tenant_variant_location_batch_key",
        "stock_balances",
        type_="unique",
    )
    op.alter_column("stock_balances", "product_id", nullable=False)
    op.alter_column("stock_movements", "product_id", nullable=False)
    op.alter_column("stock_batches", "product_id", nullable=False)
