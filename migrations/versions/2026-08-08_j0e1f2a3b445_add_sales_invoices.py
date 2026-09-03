"""add sales invoices

Revision ID: j0e1f2a3b445
Revises: i9d0e1f2a334
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j0e1f2a3b445"
down_revision: str | None = "i9d0e1f2a334"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_invoices",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_no", sa.String(length=80), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=True),
        sa.Column("location_id", sa.Uuid(), nullable=False),
        sa.Column("price_level_id", sa.Uuid(), nullable=False),
        sa.Column("invoice_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=32), server_default="draft", nullable=False),
        sa.Column("subtotal_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("discount_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("total_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("paid_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("balance_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("gross_profit", sa.Numeric(20, 4), server_default="0", nullable=False),
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
        sa.ForeignKeyConstraint(["cancelled_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["price_level_id"], ["price_levels.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["reversal_of_id"], ["sales_invoices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "document_no", name="sales_invoices_tenant_document_key"),
    )
    op.create_index(
        "sales_invoices_tenant_id_customer_id_invoice_date_idx",
        "sales_invoices",
        ["tenant_id", "customer_id", "invoice_date"],
    )
    op.create_index(
        "sales_invoices_tenant_id_location_id_invoice_date_idx",
        "sales_invoices",
        ["tenant_id", "location_id", "invoice_date"],
    )
    op.create_index(
        "sales_invoices_tenant_id_status_idx", "sales_invoices", ["tenant_id", "status"]
    )
    op.create_table(
        "sales_invoice_lines",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("sales_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=False),
        sa.Column("unit_id", sa.Uuid(), nullable=False),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("conversion_to_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("quantity_base", sa.Numeric(24, 8), nullable=False),
        sa.Column("unit_price", sa.Numeric(20, 4), nullable=False),
        sa.Column("discount_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("line_total", sa.Numeric(20, 4), nullable=False),
        sa.Column("total_cost", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("gross_profit", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("price_rule_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["price_rule_id"], ["price_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["sales_invoice_id"], ["sales_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "sales_invoice_id",
            "line_no",
            name="sales_invoice_lines_invoice_line_no_key",
        ),
    )
    op.create_index(
        "sales_invoice_lines_tenant_id_product_id_idx",
        "sales_invoice_lines",
        ["tenant_id", "product_id"],
    )


def downgrade() -> None:
    op.drop_index("sales_invoice_lines_tenant_id_product_id_idx", table_name="sales_invoice_lines")
    op.drop_table("sales_invoice_lines")
    op.drop_index("sales_invoices_tenant_id_status_idx", table_name="sales_invoices")
    op.drop_index(
        "sales_invoices_tenant_id_location_id_invoice_date_idx", table_name="sales_invoices"
    )
    op.drop_index(
        "sales_invoices_tenant_id_customer_id_invoice_date_idx", table_name="sales_invoices"
    )
    op.drop_table("sales_invoices")
