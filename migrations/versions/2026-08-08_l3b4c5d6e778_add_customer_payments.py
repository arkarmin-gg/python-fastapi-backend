"""add customer payments and receivables

Revision ID: l3b4c5d6e778
Revises: k2a3b4c5d667
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "l3b4c5d6e778"
down_revision: str | Sequence[str] | None = "k2a3b4c5d667"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_payments",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_no", sa.String(length=80), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("payment_date", sa.Date(), nullable=False),
        sa.Column("payment_method", sa.String(length=50), server_default="cash", nullable=False),
        sa.Column("amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="draft", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("posted_by", sa.Uuid(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", sa.Uuid(), nullable=True),
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
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_no",
            name="customer_payments_tenant_id_document_no_key",
        ),
    )
    op.create_index(
        "customer_payments_tenant_id_customer_id_payment_date_idx",
        "customer_payments",
        ["tenant_id", "customer_id", "payment_date"],
    )
    op.create_index(
        "customer_payments_tenant_id_status_idx",
        "customer_payments",
        ["tenant_id", "status"],
    )

    op.create_table(
        "customer_payment_allocations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_payment_id", sa.Uuid(), nullable=False),
        sa.Column("sales_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_payment_id"],
            ["customer_payments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["sales_invoice_id"], ["sales_invoices.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "customer_payment_id",
            "sales_invoice_id",
            name="customer_payment_allocations_payment_invoice_key",
        ),
    )
    op.create_index(
        "customer_payment_allocations_tenant_id_sales_invoice_id_idx",
        "customer_payment_allocations",
        ["tenant_id", "sales_invoice_id"],
    )

    op.create_table(
        "customer_ledger_entries",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.String(length=50), nullable=False),
        sa.Column("debit_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("credit_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("balance_effect", sa.Numeric(20, 4), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "customer_ledger_entries_tenant_id_customer_id_posted_at_idx",
        "customer_ledger_entries",
        ["tenant_id", "customer_id", "posted_at"],
    )
    op.create_index(
        "customer_ledger_entries_tenant_id_source_type_source_id_idx",
        "customer_ledger_entries",
        ["tenant_id", "source_type", "source_id"],
    )

    op.create_table(
        "customer_balances",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("customer_id", sa.Uuid(), nullable=False),
        sa.Column("balance_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "customer_id", name="customer_balances_tenant_customer_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("customer_balances")
    op.drop_index(
        "customer_ledger_entries_tenant_id_source_type_source_id_idx",
        table_name="customer_ledger_entries",
    )
    op.drop_index(
        "customer_ledger_entries_tenant_id_customer_id_posted_at_idx",
        table_name="customer_ledger_entries",
    )
    op.drop_table("customer_ledger_entries")
    op.drop_index(
        "customer_payment_allocations_tenant_id_sales_invoice_id_idx",
        table_name="customer_payment_allocations",
    )
    op.drop_table("customer_payment_allocations")
    op.drop_index("customer_payments_tenant_id_status_idx", table_name="customer_payments")
    op.drop_index(
        "customer_payments_tenant_id_customer_id_payment_date_idx",
        table_name="customer_payments",
    )
    op.drop_table("customer_payments")
