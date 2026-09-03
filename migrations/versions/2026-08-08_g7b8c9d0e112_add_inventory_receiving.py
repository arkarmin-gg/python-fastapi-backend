"""add inventory receiving

Revision ID: g7b8c9d0e112
Revises: f6a7b8c9d001
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g7b8c9d0e112"
down_revision: str | None = "f6a7b8c9d001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_batches",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column(
            "source_type",
            sa.Enum(
                "purchase_invoice",
                "sales_invoice",
                "stock_transfer",
                "stock_adjustment",
                "stock_count",
                "repack_order",
                "customer_payment",
                "supplier_payment",
                "manual",
                name="sourcetype",
                native_enum=False,
                length=50,
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_line_id", sa.Uuid(), nullable=True),
        sa.Column("supplier_id", sa.Uuid(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("manufactured_date", sa.Date(), nullable=True),
        sa.Column("lot_number", sa.String(length=120), nullable=True),
        sa.Column("initial_quantity_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("unit_cost_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("total_cost", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "depleted",
                "cancelled",
                name="stockbatchstatus",
                native_enum=False,
                length=50,
            ),
            server_default="active",
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="stock_batches_product_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="stock_batches_supplier_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="stock_batches_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="stock_batches_pkey"),
    )
    op.create_index(
        "stock_batches_tenant_id_product_id_received_at_idx",
        "stock_batches",
        ["tenant_id", "product_id", "received_at"],
    )
    op.create_index(
        "stock_batches_tenant_id_product_id_expiry_date_idx",
        "stock_batches",
        ["tenant_id", "product_id", "expiry_date"],
    )
    op.create_index(
        "stock_batches_tenant_id_supplier_id_idx",
        "stock_batches",
        ["tenant_id", "supplier_id"],
    )
    op.create_index(
        "stock_batches_tenant_id_source_type_source_id_idx",
        "stock_batches",
        ["tenant_id", "source_type", "source_id"],
    )
    op.create_foreign_key(
        "purchase_invoice_lines_created_stock_batch_id_fkey",
        "purchase_invoice_lines",
        "stock_batches",
        ["created_stock_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "stock_movements",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "movement_type",
            sa.Enum(
                "purchase_receive",
                "sale_issue",
                "transfer_out",
                "transfer_in",
                "repack_input",
                "repack_output",
                "adjustment",
                "count_adjustment",
                "damage_loss",
                "reversal",
                name="stockmovementtype",
                native_enum=False,
                length=50,
            ),
            nullable=False,
        ),
        sa.Column(
            "source_type",
            sa.Enum(
                "purchase_invoice",
                "sales_invoice",
                "stock_transfer",
                "stock_adjustment",
                "stock_count",
                "repack_order",
                "customer_payment",
                "supplier_payment",
                "manual",
                name="sourcetype",
                native_enum=False,
                length=50,
            ),
            nullable=False,
        ),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("source_line_id", sa.Uuid(), nullable=True),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("stock_batch_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("quantity_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("unit_cost_base", sa.Numeric(precision=24, scale=8), nullable=True),
        sa.Column("total_cost", sa.Numeric(precision=20, scale=4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name="stock_movements_location_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["posted_by"],
            ["users.id"],
            name="stock_movements_posted_by_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="stock_movements_product_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stock_batch_id"],
            ["stock_batches.id"],
            name="stock_movements_stock_batch_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="stock_movements_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="stock_movements_pkey"),
    )
    op.create_index(
        "stock_movements_tenant_product_location_posted_idx",
        "stock_movements",
        ["tenant_id", "product_id", "location_id", "posted_at"],
    )
    op.create_index(
        "stock_movements_tenant_id_stock_batch_id_posted_at_idx",
        "stock_movements",
        ["tenant_id", "stock_batch_id", "posted_at"],
    )
    op.create_index(
        "stock_movements_tenant_id_source_type_source_id_idx",
        "stock_movements",
        ["tenant_id", "source_type", "source_id"],
    )
    op.create_index(
        "stock_movements_tenant_id_movement_type_posted_at_idx",
        "stock_movements",
        ["tenant_id", "movement_type", "posted_at"],
    )

    op.create_table(
        "stock_balances",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("stock_batch_id", sa.Uuid(), nullable=False),
        sa.Column(
            "quantity_base",
            sa.Numeric(precision=24, scale=8),
            server_default="0",
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["location_id"],
            ["locations.id"],
            name="stock_balances_location_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="stock_balances_product_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stock_batch_id"],
            ["stock_batches.id"],
            name="stock_balances_stock_batch_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="stock_balances_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="stock_balances_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "product_id",
            "location_id",
            "stock_batch_id",
            name="stock_balances_tenant_product_location_batch_key",
        ),
    )
    op.create_index(
        "stock_balances_tenant_id_product_id_location_id_idx",
        "stock_balances",
        ["tenant_id", "product_id", "location_id"],
    )
    op.create_index(
        "stock_balances_tenant_id_stock_batch_id_idx",
        "stock_balances",
        ["tenant_id", "stock_batch_id"],
    )


def downgrade() -> None:
    op.drop_index("stock_balances_tenant_id_stock_batch_id_idx", table_name="stock_balances")
    op.drop_index(
        "stock_balances_tenant_id_product_id_location_id_idx",
        table_name="stock_balances",
    )
    op.drop_table("stock_balances")
    op.drop_index(
        "stock_movements_tenant_id_movement_type_posted_at_idx",
        table_name="stock_movements",
    )
    op.drop_index(
        "stock_movements_tenant_id_source_type_source_id_idx",
        table_name="stock_movements",
    )
    op.drop_index(
        "stock_movements_tenant_id_stock_batch_id_posted_at_idx",
        table_name="stock_movements",
    )
    op.drop_index(
        "stock_movements_tenant_product_location_posted_idx",
        table_name="stock_movements",
    )
    op.drop_table("stock_movements")
    op.drop_constraint(
        "purchase_invoice_lines_created_stock_batch_id_fkey",
        "purchase_invoice_lines",
        type_="foreignkey",
    )
    op.drop_index(
        "stock_batches_tenant_id_source_type_source_id_idx",
        table_name="stock_batches",
    )
    op.drop_index("stock_batches_tenant_id_supplier_id_idx", table_name="stock_batches")
    op.drop_index(
        "stock_batches_tenant_id_product_id_expiry_date_idx",
        table_name="stock_batches",
    )
    op.drop_index(
        "stock_batches_tenant_id_product_id_received_at_idx",
        table_name="stock_batches",
    )
    op.drop_table("stock_batches")
