"""add purchase invoices

Revision ID: f6a7b8c9d001
Revises: e5f6a7b8c990
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f6a7b8c9d001"
down_revision: str | None = "e5f6a7b8c990"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "purchase_invoices",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_no", sa.String(length=80), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("receiving_location_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("supplier_invoice_no", sa.String(length=120), nullable=True),
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
        sa.Column(
            "subtotal_amount",
            sa.Numeric(precision=20, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "landed_cost_amount",
            sa.Numeric(precision=20, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_amount",
            sa.Numeric(precision=20, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "paid_amount",
            sa.Numeric(precision=20, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "balance_amount",
            sa.Numeric(precision=20, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
        sa.Column("reversal_of_id", sa.Uuid(), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["cancelled_by"],
            ["users.id"],
            name="purchase_invoices_cancelled_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="purchase_invoices_created_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["posted_by"],
            ["users.id"],
            name="purchase_invoices_posted_by_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["receiving_location_id"],
            ["locations.id"],
            name="purchase_invoices_receiving_location_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reversal_of_id"],
            ["purchase_invoices.id"],
            name="purchase_invoices_reversal_of_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name="purchase_invoices_supplier_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="purchase_invoices_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="purchase_invoices_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_no",
            name="purchase_invoices_tenant_id_document_no_key",
        ),
    )
    op.create_index(
        "purchase_invoices_tenant_id_supplier_id_invoice_date_idx",
        "purchase_invoices",
        ["tenant_id", "supplier_id", "invoice_date"],
    )
    op.create_index(
        "purchase_invoices_tenant_id_receiving_location_id_idx",
        "purchase_invoices",
        ["tenant_id", "receiving_location_id"],
    )
    op.create_index(
        "purchase_invoices_tenant_id_status_idx",
        "purchase_invoices",
        ["tenant_id", "status"],
    )
    op.create_table(
        "purchase_invoice_lines",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("quantity_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column("line_amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column(
            "allocated_landed_cost",
            sa.Numeric(precision=20, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "total_line_cost",
            sa.Numeric(precision=20, scale=4),
            server_default="0",
            nullable=False,
        ),
        sa.Column("unit_cost_base", sa.Numeric(precision=24, scale=8), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("manufactured_date", sa.Date(), nullable=True),
        sa.Column("lot_number", sa.String(length=120), nullable=True),
        sa.Column("created_stock_batch_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name="purchase_invoice_lines_product_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_invoice_id"],
            ["purchase_invoices.id"],
            name="purchase_invoice_lines_purchase_invoice_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="purchase_invoice_lines_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unit_id"],
            ["units.id"],
            name="purchase_invoice_lines_unit_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="purchase_invoice_lines_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "purchase_invoice_id",
            "line_no",
            name="purchase_invoice_lines_invoice_line_no_key",
        ),
    )
    op.create_index(
        "purchase_invoice_lines_tenant_id_product_id_idx",
        "purchase_invoice_lines",
        ["tenant_id", "product_id"],
    )
    op.create_table(
        "purchase_landed_costs",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_invoice_id", sa.Uuid(), nullable=False),
        sa.Column(
            "cost_type",
            sa.Enum(
                "transport",
                "loading",
                "unloading",
                "customs",
                "tax",
                "other",
                name="purchaselandedcosttype",
                native_enum=False,
                length=50,
            ),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(precision=20, scale=4), nullable=False),
        sa.Column(
            "allocation_method",
            sa.Enum(
                "by_value",
                "by_base_quantity",
                "manual",
                name="landedcostallocationmethod",
                native_enum=False,
                length=50,
            ),
            server_default="by_value",
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["purchase_invoice_id"],
            ["purchase_invoices.id"],
            name="purchase_landed_costs_purchase_invoice_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="purchase_landed_costs_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="purchase_landed_costs_pkey"),
    )
    op.create_index(
        "purchase_landed_costs_tenant_id_purchase_invoice_id_idx",
        "purchase_landed_costs",
        ["tenant_id", "purchase_invoice_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "purchase_landed_costs_tenant_id_purchase_invoice_id_idx",
        table_name="purchase_landed_costs",
    )
    op.drop_table("purchase_landed_costs")
    op.drop_index(
        "purchase_invoice_lines_tenant_id_product_id_idx",
        table_name="purchase_invoice_lines",
    )
    op.drop_table("purchase_invoice_lines")
    op.drop_index("purchase_invoices_tenant_id_status_idx", table_name="purchase_invoices")
    op.drop_index(
        "purchase_invoices_tenant_id_receiving_location_id_idx",
        table_name="purchase_invoices",
    )
    op.drop_index(
        "purchase_invoices_tenant_id_supplier_id_invoice_date_idx",
        table_name="purchase_invoices",
    )
    op.drop_table("purchase_invoices")
