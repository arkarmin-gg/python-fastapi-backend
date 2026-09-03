"""add locations

Revision ID: d4e5f6a7b889
Revises: c3f4a5b6d778
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b889"
down_revision: str | None = "c3f4a5b6d778"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "locations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("parent_location_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=180), nullable=False),
        sa.Column(
            "location_type",
            sa.Enum(
                "warehouse",
                "store",
                "sub_warehouse",
                "counter",
                "damaged",
                "in_transit",
                "virtual",
                name="locationtype",
                native_enum=False,
                length=50,
            ),
            nullable=False,
        ),
        sa.Column("is_sellable", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["parent_location_id"],
            ["locations.id"],
            name="locations_parent_location_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="locations_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="locations_pkey"),
        sa.UniqueConstraint("tenant_id", "code", name="locations_tenant_id_code_key"),
    )
    op.create_index(
        "locations_tenant_id_parent_location_id_idx",
        "locations",
        ["tenant_id", "parent_location_id"],
    )
    op.create_index(
        "locations_tenant_id_location_type_idx",
        "locations",
        ["tenant_id", "location_type"],
    )


def downgrade() -> None:
    op.drop_index("locations_tenant_id_location_type_idx", table_name="locations")
    op.drop_index("locations_tenant_id_parent_location_id_idx", table_name="locations")
    op.drop_table("locations")
