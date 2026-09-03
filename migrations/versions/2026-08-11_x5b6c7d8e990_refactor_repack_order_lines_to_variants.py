"""refactor repack order lines to variants

Revision ID: x5b6c7d8e990
Revises: w4a5b6c7d889
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "x5b6c7d8e990"
down_revision: str | Sequence[str] | None = "w4a5b6c7d889"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM repack_order_inputs")
    op.execute("DELETE FROM repack_order_outputs")

    op.add_column(
        "repack_order_inputs",
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
    )
    op.add_column(
        "repack_order_inputs",
        sa.Column("variant_unit_id", sa.Uuid(), nullable=False),
    )
    op.alter_column("repack_order_inputs", "product_id", nullable=True)
    op.alter_column("repack_order_inputs", "unit_id", nullable=True)
    op.create_foreign_key(
        "repack_order_inputs_product_variant_id_fkey",
        "repack_order_inputs",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "repack_order_inputs_variant_unit_id_fkey",
        "repack_order_inputs",
        "variant_units",
        ["variant_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "repack_order_inputs_tenant_id_product_variant_id_idx",
        "repack_order_inputs",
        ["tenant_id", "product_variant_id"],
        unique=False,
    )
    op.create_index(
        "repack_order_inputs_tenant_id_variant_unit_id_idx",
        "repack_order_inputs",
        ["tenant_id", "variant_unit_id"],
        unique=False,
    )

    op.add_column(
        "repack_order_outputs",
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
    )
    op.add_column(
        "repack_order_outputs",
        sa.Column("variant_unit_id", sa.Uuid(), nullable=False),
    )
    op.alter_column("repack_order_outputs", "product_id", nullable=True)
    op.alter_column("repack_order_outputs", "unit_id", nullable=True)
    op.create_foreign_key(
        "repack_order_outputs_product_variant_id_fkey",
        "repack_order_outputs",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "repack_order_outputs_variant_unit_id_fkey",
        "repack_order_outputs",
        "variant_units",
        ["variant_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "repack_order_outputs_tenant_id_product_variant_id_idx",
        "repack_order_outputs",
        ["tenant_id", "product_variant_id"],
        unique=False,
    )
    op.create_index(
        "repack_order_outputs_tenant_id_variant_unit_id_idx",
        "repack_order_outputs",
        ["tenant_id", "variant_unit_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "repack_order_outputs_tenant_id_variant_unit_id_idx",
        table_name="repack_order_outputs",
    )
    op.drop_index(
        "repack_order_outputs_tenant_id_product_variant_id_idx",
        table_name="repack_order_outputs",
    )
    op.drop_constraint(
        "repack_order_outputs_variant_unit_id_fkey",
        "repack_order_outputs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "repack_order_outputs_product_variant_id_fkey",
        "repack_order_outputs",
        type_="foreignkey",
    )
    op.alter_column("repack_order_outputs", "unit_id", nullable=False)
    op.alter_column("repack_order_outputs", "product_id", nullable=False)
    op.drop_column("repack_order_outputs", "variant_unit_id")
    op.drop_column("repack_order_outputs", "product_variant_id")

    op.drop_index(
        "repack_order_inputs_tenant_id_variant_unit_id_idx",
        table_name="repack_order_inputs",
    )
    op.drop_index(
        "repack_order_inputs_tenant_id_product_variant_id_idx",
        table_name="repack_order_inputs",
    )
    op.drop_constraint(
        "repack_order_inputs_variant_unit_id_fkey",
        "repack_order_inputs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "repack_order_inputs_product_variant_id_fkey",
        "repack_order_inputs",
        type_="foreignkey",
    )
    op.alter_column("repack_order_inputs", "unit_id", nullable=False)
    op.alter_column("repack_order_inputs", "product_id", nullable=False)
    op.drop_column("repack_order_inputs", "variant_unit_id")
    op.drop_column("repack_order_inputs", "product_variant_id")
