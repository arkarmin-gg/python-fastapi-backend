"""Add variant identity to inventory rows.

Revision ID: t1d2e3f4a556
Revises: s0c1d2e3f445
Create Date: 2026-08-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "t1d2e3f4a556"
down_revision: str | Sequence[str] | None = "s0c1d2e3f445"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stock_batches", sa.Column("product_variant_id", sa.Uuid(), nullable=True))
    op.add_column("stock_movements", sa.Column("product_variant_id", sa.Uuid(), nullable=True))
    op.add_column("stock_balances", sa.Column("product_variant_id", sa.Uuid(), nullable=True))

    op.create_foreign_key(
        "stock_batches_product_variant_id_fkey",
        "stock_batches",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "stock_movements_product_variant_id_fkey",
        "stock_movements",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "stock_balances_product_variant_id_fkey",
        "stock_balances",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_index(
        "stock_batches_tenant_id_product_variant_id_received_at_idx",
        "stock_batches",
        ["tenant_id", "product_variant_id", "received_at"],
    )
    op.create_index(
        "stock_movements_tenant_variant_location_posted_idx",
        "stock_movements",
        ["tenant_id", "product_variant_id", "location_id", "posted_at"],
    )
    op.create_index(
        "stock_balances_tenant_id_product_variant_id_location_id_idx",
        "stock_balances",
        ["tenant_id", "product_variant_id", "location_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "stock_balances_tenant_id_product_variant_id_location_id_idx",
        table_name="stock_balances",
    )
    op.drop_index(
        "stock_movements_tenant_variant_location_posted_idx",
        table_name="stock_movements",
    )
    op.drop_index(
        "stock_batches_tenant_id_product_variant_id_received_at_idx",
        table_name="stock_batches",
    )

    op.drop_constraint(
        "stock_balances_product_variant_id_fkey",
        "stock_balances",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_movements_product_variant_id_fkey",
        "stock_movements",
        type_="foreignkey",
    )
    op.drop_constraint(
        "stock_batches_product_variant_id_fkey",
        "stock_batches",
        type_="foreignkey",
    )

    op.drop_column("stock_balances", "product_variant_id")
    op.drop_column("stock_movements", "product_variant_id")
    op.drop_column("stock_batches", "product_variant_id")
