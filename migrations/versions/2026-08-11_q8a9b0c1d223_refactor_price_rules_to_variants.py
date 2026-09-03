"""refactor price rules to product variants

Revision ID: q8a9b0c1d223
Revises: p7f8a9b0c112
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "q8a9b0c1d223"
down_revision: str | None = "p7f8a9b0c112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("price_rules", sa.Column("product_variant_id", sa.Uuid(), nullable=True))
    op.add_column("price_rules", sa.Column("variant_unit_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "price_rules_product_variant_id_fkey",
        "price_rules",
        "product_variants",
        ["product_variant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "price_rules_variant_unit_id_fkey",
        "price_rules",
        "variant_units",
        ["variant_unit_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "price_rules_variant_scope_effective_from_idx",
        "price_rules",
        [
            "tenant_id",
            "product_variant_id",
            "variant_unit_id",
            "price_level_id",
            "effective_from",
        ],
    )


def downgrade() -> None:
    op.drop_index("price_rules_variant_scope_effective_from_idx", table_name="price_rules")
    op.drop_constraint("price_rules_variant_unit_id_fkey", "price_rules", type_="foreignkey")
    op.drop_constraint("price_rules_product_variant_id_fkey", "price_rules", type_="foreignkey")
    op.drop_column("price_rules", "variant_unit_id")
    op.drop_column("price_rules", "product_variant_id")
