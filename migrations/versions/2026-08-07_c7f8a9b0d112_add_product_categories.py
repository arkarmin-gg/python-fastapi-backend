"""add tenant-scoped product categories

Revision ID: c7f8a9b0d112
Revises: b6e7f8a9c001
Create Date: 2026-08-07 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7f8a9b0d112"
down_revision: str | None = "b6e7f8a9c001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "product_categories",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("parent_category_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=50), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["parent_category_id"],
            ["product_categories.id"],
            name="product_categories_parent_category_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="product_categories_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="product_categories_pkey"),
        sa.UniqueConstraint("tenant_id", "code", name="product_categories_tenant_id_code_key"),
    )
    op.create_index(
        "product_categories_tenant_id_parent_category_id_idx",
        "product_categories",
        ["tenant_id", "parent_category_id"],
    )
    op.create_index(
        "product_categories_tenant_id_name_idx",
        "product_categories",
        ["tenant_id", "name"],
    )
    op.create_index(
        "product_categories_tenant_id_is_active_idx",
        "product_categories",
        ["tenant_id", "is_active"],
    )


def downgrade() -> None:
    op.drop_index("product_categories_tenant_id_is_active_idx", table_name="product_categories")
    op.drop_index("product_categories_tenant_id_name_idx", table_name="product_categories")
    op.drop_index(
        "product_categories_tenant_id_parent_category_id_idx",
        table_name="product_categories",
    )
    op.drop_table("product_categories")
