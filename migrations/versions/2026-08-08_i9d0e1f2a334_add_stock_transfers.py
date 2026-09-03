"""add stock transfers

Revision ID: i9d0e1f2a334
Revises: h8c9d0e1f223
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i9d0e1f2a334"
down_revision: str | None = "h8c9d0e1f223"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_transfers",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_no", sa.String(length=80), nullable=False),
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
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
            name="stock_transfers_cancelled_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["posted_by"],
            ["users.id"],
            name="stock_transfers_posted_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by"],
            ["users.id"],
            name="stock_transfers_requested_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"],
            ["stock_transfers.id"],
            name="stock_transfers_reversal_of_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="stock_transfers_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="stock_transfers_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_no",
            name="stock_transfers_tenant_id_document_no_key",
        ),
    )
    op.create_index(
        "stock_transfers_tenant_id_status_idx",
        "stock_transfers",
        ["tenant_id", "status"],
    )

    op.create_table(
        "stock_transfer_lines",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("stock_transfer_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("stock_batch_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("quantity_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("from_location_id", sa.Uuid(), nullable=False),
        sa.Column("to_location_id", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["from_location_id"],
            ["locations.id"],
            name="stock_transfer_lines_from_location_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="stock_transfer_lines_product_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stock_batch_id"],
            ["stock_batches.id"],
            name="stock_transfer_lines_stock_batch_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stock_transfer_id"],
            ["stock_transfers.id"],
            name="stock_transfer_lines_stock_transfer_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="stock_transfer_lines_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_location_id"],
            ["locations.id"],
            name="stock_transfer_lines_to_location_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="stock_transfer_lines_unit_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="stock_transfer_lines_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "stock_transfer_id",
            "line_no",
            name="stock_transfer_lines_transfer_line_no_key",
        ),
    )
    op.create_index(
        "stock_transfer_lines_tenant_id_from_location_id_idx",
        "stock_transfer_lines",
        ["tenant_id", "from_location_id"],
    )
    op.create_index(
        "stock_transfer_lines_tenant_id_to_location_id_idx",
        "stock_transfer_lines",
        ["tenant_id", "to_location_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "stock_transfer_lines_tenant_id_to_location_id_idx",
        table_name="stock_transfer_lines",
    )
    op.drop_index(
        "stock_transfer_lines_tenant_id_from_location_id_idx",
        table_name="stock_transfer_lines",
    )
    op.drop_table("stock_transfer_lines")
    op.drop_index("stock_transfers_tenant_id_status_idx", table_name="stock_transfers")
    op.drop_table("stock_transfers")
