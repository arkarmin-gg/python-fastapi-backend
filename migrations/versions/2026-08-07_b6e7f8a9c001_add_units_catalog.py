"""add globally managed units catalog

Revision ID: b6e7f8a9c001
Revises: 407f2d770c8a
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6e7f8a9c001"
down_revision: str | None = "407f2d770c8a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "units",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("name_en", sa.String(length=120), nullable=False),
        sa.Column("name_my", sa.String(length=120), nullable=True),
        sa.Column("unit_kind", sa.String(length=50), nullable=False),
        sa.Column("is_global", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.PrimaryKeyConstraint("id", name="units_pkey"),
        sa.UniqueConstraint("code", name="units_code_key"),
    )
    op.create_index("units_code_idx", "units", ["code"])
    op.create_index("units_unit_kind_idx", "units", ["unit_kind"])
    op.create_index("units_is_active_idx", "units", ["is_active"])


def downgrade() -> None:
    op.drop_index("units_is_active_idx", table_name="units")
    op.drop_index("units_unit_kind_idx", table_name="units")
    op.drop_index("units_code_idx", table_name="units")
    op.drop_table("units")
