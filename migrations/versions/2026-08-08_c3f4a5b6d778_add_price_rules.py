"""add price rules

Revision ID: c3f4a5b6d778
Revises: b2e3f4a5c667
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3f4a5b6d778"
down_revision: str | None = "b2e3f4a5c667"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_rules",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("price_level_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("min_quantity", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("currency_code", sa.String(length=3), server_default="MMK", nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name="price_rules_customer_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["price_level_id"],
            ["price_levels.id"],
            name="price_rules_price_level_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="price_rules_product_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="price_rules_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="price_rules_unit_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="price_rules_pkey"),
    )
    op.create_index(
        "price_rules_scope_effective_from_idx",
        "price_rules",
        ["tenant_id", "product_id", "unit_id", "price_level_id", "effective_from"],
    )
    op.create_index(
        "price_rules_tenant_id_customer_id_idx",
        "price_rules",
        ["tenant_id", "customer_id"],
    )


def downgrade() -> None:
    op.drop_index("price_rules_tenant_id_customer_id_idx", table_name="price_rules")
    op.drop_index(
        "price_rules_scope_effective_from_idx",
        table_name="price_rules",
    )
    op.drop_table("price_rules")
