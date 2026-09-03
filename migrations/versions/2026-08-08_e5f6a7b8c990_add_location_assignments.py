"""add location assignments

Revision ID: e5f6a7b8c990
Revises: d4e5f6a7b889
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c990"
down_revision: str | None = "d4e5f6a7b889"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "location_assignments",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "responsible",
                "assistant",
                "checker",
                name="assignmentrole",
                native_enum=False,
                length=50,
            ),
            server_default="responsible",
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["employee_id"],
            ["employees.id"],
            name="location_assignments_employee_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name="location_assignments_location_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="location_assignments_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="location_assignments_pkey"),
    )
    op.create_index(
        "location_assignments_tenant_id_location_id_start_date_idx",
        "location_assignments",
        ["tenant_id", "location_id", "start_date"],
    )
    op.create_index(
        "location_assignments_tenant_id_employee_id_start_date_idx",
        "location_assignments",
        ["tenant_id", "employee_id", "start_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "location_assignments_tenant_id_employee_id_start_date_idx",
        table_name="location_assignments",
    )
    op.drop_index(
        "location_assignments_tenant_id_location_id_start_date_idx",
        table_name="location_assignments",
    )
    op.drop_table("location_assignments")
