"""add tenant-scoped price levels

Revision ID: d8a9b0c1e223
Revises: c7f8a9b0d112
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d8a9b0c1e223"
down_revision: str | None = "c7f8a9b0d112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "price_levels",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="price_levels_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="price_levels_pkey"),
        sa.UniqueConstraint("tenant_id", "code", name="price_levels_tenant_id_code_key"),
    )
    op.create_index("price_levels_tenant_id_name_idx", "price_levels", ["tenant_id", "name"])
    op.create_index(
        "price_levels_tenant_id_is_default_idx",
        "price_levels",
        ["tenant_id", "is_default"],
    )
    op.create_index(
        "price_levels_tenant_id_is_active_idx",
        "price_levels",
        ["tenant_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("price_levels_tenant_id_is_active_idx", table_name="price_levels")
    op.drop_index("price_levels_tenant_id_is_default_idx", table_name="price_levels")
    op.drop_index("price_levels_tenant_id_name_idx", table_name="price_levels")
    op.drop_table("price_levels")
