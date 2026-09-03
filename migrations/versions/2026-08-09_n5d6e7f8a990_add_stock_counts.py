"""add stock counts

Revision ID: n5d6e7f8a990
Revises: m4c5d6e7f889
Create Date: 2026-08-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "n5d6e7f8a990"
down_revision: str | Sequence[str] | None = "m4c5d6e7f889"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_counts",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_no", sa.String(length=80), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("counted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("counted_by", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="draft", nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["counted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "document_no", name="stock_counts_tenant_id_document_no_key"
        ),
    )
    op.create_index(
        "stock_counts_tenant_id_location_counted_at_idx",
        "stock_counts",
        ["tenant_id", "location_id", "counted_at"],
    )
    op.create_index(
        "stock_counts_tenant_id_status_idx",
        "stock_counts",
        ["tenant_id", "status"],
    )

    op.create_table(
        "stock_count_lines",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stock_count_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("stock_batch_id", sa.Uuid(), nullable=False),
        sa.Column("expected_quantity_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("counted_quantity_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("variance_quantity_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("adjustment_movement_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["adjustment_movement_id"],
            ["stock_movements.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stock_batch_id"], ["stock_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["stock_count_id"], ["stock_counts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "stock_count_id",
            "line_no",
            name="stock_count_lines_count_line_no_key",
        ),
    )
    op.create_index(
        "stock_count_lines_tenant_product_batch_idx",
        "stock_count_lines",
        ["tenant_id", "product_id", "stock_batch_id"],
    )
    op.create_index(
        "stock_count_lines_tenant_adjustment_movement_idx",
        "stock_count_lines",
        ["tenant_id", "adjustment_movement_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "stock_count_lines_tenant_adjustment_movement_idx",
        table_name="stock_count_lines",
    )
    op.drop_index("stock_count_lines_tenant_product_batch_idx", table_name="stock_count_lines")
    op.drop_table("stock_count_lines")
    op.drop_index("stock_counts_tenant_id_status_idx", table_name="stock_counts")
    op.drop_index("stock_counts_tenant_id_location_counted_at_idx", table_name="stock_counts")
    op.drop_table("stock_counts")
