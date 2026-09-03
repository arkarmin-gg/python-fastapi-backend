"""add stock adjustments

Revision ID: h8c9d0e1f223
Revises: g7b8c9d0e112
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h8c9d0e1f223"
down_revision: str | None = "g7b8c9d0e112"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_adjustments",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_no", sa.String(length=80), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column(
            "reason",
            sa.Enum(
                "count_variance",
                "damage",
                "loss",
                "expiry",
                "correction",
                "opening_balance",
                "other",
                name="stockadjustmentreason",
                native_enum=False,
                length=50,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "pending_approval",
                "approved",
                "posted",
                "cancelled",
                "reversed",
                "rejected",
                name="documentstatus",
                native_enum=False,
                length=50,
            ),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["cancelled_by"],
            ["users.id"],
            name="stock_adjustments_cancelled_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="stock_adjustments_created_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name="stock_adjustments_location_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posted_by"],
            ["users.id"],
            name="stock_adjustments_posted_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="stock_adjustments_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="stock_adjustments_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_no",
            name="stock_adjustments_tenant_id_document_no_key",
        ),
    )
    op.create_index(
        "stock_adjustments_tenant_id_location_id_idx",
        "stock_adjustments",
        ["tenant_id", "location_id"],
    )
    op.create_index(
        "stock_adjustments_tenant_id_status_idx",
        "stock_adjustments",
        ["tenant_id", "status"],
    )

    op.create_table(
        "stock_adjustment_lines",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stock_adjustment_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("stock_batch_id", sa.Uuid(), nullable=True),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("quantity_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("unit_cost_base", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("manufactured_date", sa.Date(), nullable=True),
        sa.Column("lot_number", sa.String(length=120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="stock_adjustment_lines_product_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stock_adjustment_id"],
            ["stock_adjustments.id"],
            name="stock_adjustment_lines_stock_adjustment_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_batch_id"],
            ["stock_batches.id"],
            name="stock_adjustment_lines_stock_batch_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="stock_adjustment_lines_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="stock_adjustment_lines_unit_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="stock_adjustment_lines_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "stock_adjustment_id",
            "line_no",
            name="stock_adjustment_lines_adjustment_line_no_key",
        ),
    )
    op.create_index(
        "stock_adjustment_lines_tenant_id_product_id_idx",
        "stock_adjustment_lines",
        ["tenant_id", "product_id"],
    )
    op.create_index(
        "stock_adjustment_lines_tenant_id_stock_batch_id_idx",
        "stock_adjustment_lines",
        ["tenant_id", "stock_batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "stock_adjustment_lines_tenant_id_stock_batch_id_idx",
        table_name="stock_adjustment_lines",
    )
    op.drop_index(
        "stock_adjustment_lines_tenant_id_product_id_idx",
        table_name="stock_adjustment_lines",
    )
    op.drop_table("stock_adjustment_lines")
    op.drop_index("stock_adjustments_tenant_id_status_idx", table_name="stock_adjustments")
    op.drop_index("stock_adjustments_tenant_id_location_id_idx", table_name="stock_adjustments")
    op.drop_table("stock_adjustments")
