"""add customers

Revision ID: a1d2e3f4b556
Revises: f0c1d2e3a445
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1d2e3f4b556"
down_revision: str | None = "f0c1d2e3a445"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column(
            "customer_type",
            sa.Enum(
                "walk_in",
                "retail",
                "wholesale",
                "restaurant",
                "hotel",
                "reseller",
                "other",
                native_enum=False,
                length=50,
            ),
            server_default="retail",
            nullable=False,
        ),
        sa.Column("price_level_id", sa.Uuid(), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("credit_limit", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "inactive",
                "blocked",
                native_enum=False,
                length=50,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["price_level_id"],
            ["price_levels.id"],
            name="customers_price_level_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="customers_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="customers_pkey"),
        sa.UniqueConstraint("tenant_id", "code", name="customers_tenant_id_code_key"),
    )
    op.create_index("customers_tenant_id_name_idx", "customers", ["tenant_id", "name"])
    op.create_index(
        "customers_tenant_id_price_level_id_idx",
        "customers",
        ["tenant_id", "price_level_id"],
    )


def downgrade() -> None:
    op.drop_index("customers_tenant_id_price_level_id_idx", table_name="customers")
    op.drop_index("customers_tenant_id_name_idx", table_name="customers")
    op.drop_table("customers")
