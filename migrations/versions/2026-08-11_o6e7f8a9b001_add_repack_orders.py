"""add repack orders

Revision ID: o6e7f8a9b001
Revises: n5d6e7f8a990
Create Date: 2026-08-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "o6e7f8a9b001"
down_revision: str | Sequence[str] | None = "n5d6e7f8a990"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "repack_orders",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_no", sa.String(length=80), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="draft", nullable=False),
        sa.Column("performed_by", sa.Uuid(), nullable=True),
        sa.Column("total_input_cost", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("total_output_cost", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("waste_cost", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["performed_by"], ["employees.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["repack_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_no",
            name="repack_orders_tenant_id_document_no_key",
        ),
    )
    op.create_index(
        "repack_orders_tenant_id_location_id_idx",
        "repack_orders",
        ["tenant_id", "location_id"],
    )
    op.create_index(
        "repack_orders_tenant_id_performed_by_idx",
        "repack_orders",
        ["tenant_id", "performed_by"],
    )
    op.create_index(
        "repack_orders_tenant_id_status_idx",
        "repack_orders",
        ["tenant_id", "status"],
    )

    op.create_table(
        "repack_order_inputs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("repack_order_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("stock_batch_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("quantity_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit_cost_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 4), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repack_order_id"], ["repack_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stock_batch_id"], ["stock_batches.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "repack_order_id",
            "line_no",
            name="repack_order_inputs_order_line_no_key",
        ),
    )
    op.create_index(
        "repack_order_inputs_tenant_id_stock_batch_id_idx",
        "repack_order_inputs",
        ["tenant_id", "stock_batch_id"],
    )

    op.create_table(
        "repack_order_outputs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("repack_order_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("quantity_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("allocated_cost", sa.Numeric(20, 4), nullable=False),
        sa.Column("unit_cost_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("lot_number", sa.String(length=120), nullable=True),
        sa.Column("created_stock_batch_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_stock_batch_id"], ["stock_batches.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["repack_order_id"], ["repack_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "repack_order_id",
            "line_no",
            name="repack_order_outputs_order_line_no_key",
        ),
    )
    op.create_index(
        "repack_order_outputs_tenant_created_stock_batch_idx",
        "repack_order_outputs",
        ["tenant_id", "created_stock_batch_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "repack_order_outputs_tenant_created_stock_batch_idx",
        table_name="repack_order_outputs",
    )
    op.drop_table("repack_order_outputs")
    op.drop_index(
        "repack_order_inputs_tenant_id_stock_batch_id_idx",
        table_name="repack_order_inputs",
    )
    op.drop_table("repack_order_inputs")
    op.drop_index("repack_orders_tenant_id_status_idx", table_name="repack_orders")
    op.drop_index("repack_orders_tenant_id_performed_by_idx", table_name="repack_orders")
    op.drop_index("repack_orders_tenant_id_location_id_idx", table_name="repack_orders")
    op.drop_table("repack_orders")
