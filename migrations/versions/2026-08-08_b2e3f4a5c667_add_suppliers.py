"""add suppliers

Revision ID: b2e3f4a5c667
Revises: a1d2e3f4b556
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2e3f4a5c667"
down_revision: str | None = "a1d2e3f4b556"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=240), nullable=False),
        sa.Column(
            "supplier_type",
            sa.Enum(
                "local",
                "importer",
                "wholesaler",
                "manufacturer",
                "other",
                native_enum=False,
                length=50,
            ),
            server_default="local",
            nullable=False,
        ),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
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
            ["tenant_id"],
            ["tenants.id"],
            name="suppliers_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="suppliers_pkey"),
        sa.UniqueConstraint("tenant_id", "code", name="suppliers_tenant_id_code_key"),
    )
    op.create_index("suppliers_tenant_id_name_idx", "suppliers", ["tenant_id", "name"])


def downgrade() -> None:
    op.drop_index("suppliers_tenant_id_name_idx", table_name="suppliers")
    op.drop_table("suppliers")
