"""add supplier payments and payables

Revision ID: m4c5d6e7f889
Revises: l3b4c5d6e778
Create Date: 2026-08-09 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m4c5d6e7f889"
down_revision: str | Sequence[str] | None = "l3b4c5d6e778"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplier_payments",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_no", sa.String(length=80), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
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
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_no",
            name="supplier_payments_tenant_id_document_no_key",
        ),
    )
    op.create_index(
        "supplier_payments_tenant_id_supplier_id_payment_date_idx",
        "supplier_payments",
        ["tenant_id", "supplier_id", "payment_date"],
    )
    op.create_index(
        "supplier_payments_tenant_id_status_idx",
        "supplier_payments",
        ["tenant_id", "status"],
    )

    op.create_table(
        "supplier_payment_allocations",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_payment_id", sa.Uuid(), nullable=False),
        sa.Column("purchase_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("allocated_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["purchase_invoice_id"],
            ["purchase_invoices.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_payment_id"],
            ["supplier_payments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "supplier_payment_id",
            "purchase_invoice_id",
            name="supplier_payment_allocations_payment_invoice_key",
        ),
    )
    op.create_index(
        "supplier_payment_allocations_tenant_id_purchase_invoice_id_idx",
        "supplier_payment_allocations",
        ["tenant_id", "purchase_invoice_id"],
    )

    op.create_table(
        "supplier_ledger_entries",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("entry_type", sa.String(length=50), nullable=False),
        sa.Column("debit_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("credit_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("balance_effect", sa.Numeric(20, 4), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("posted_by", sa.Uuid(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "supplier_ledger_entries_tenant_id_supplier_id_posted_at_idx",
        "supplier_ledger_entries",
        ["tenant_id", "supplier_id", "posted_at"],
    )
    op.create_index(
        "supplier_ledger_entries_tenant_id_source_type_source_id_idx",
        "supplier_ledger_entries",
        ["tenant_id", "source_type", "source_id"],
    )

    op.create_table(
        "supplier_balances",
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("supplier_id", sa.Uuid(), nullable=False),
        sa.Column("balance_amount", sa.Numeric(20, 4), server_default="0", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id", "supplier_id", name="supplier_balances_tenant_supplier_key"
        ),
    )


def downgrade() -> None:
    op.drop_table("supplier_balances")
    op.drop_index(
        "supplier_ledger_entries_tenant_id_source_type_source_id_idx",
        table_name="supplier_ledger_entries",
    )
    op.drop_index(
        "supplier_ledger_entries_tenant_id_supplier_id_posted_at_idx",
        table_name="supplier_ledger_entries",
    )
    op.drop_table("supplier_ledger_entries")
    op.drop_index(
        "supplier_payment_allocations_tenant_id_purchase_invoice_id_idx",
        table_name="supplier_payment_allocations",
    )
    op.drop_table("supplier_payment_allocations")
    op.drop_index("supplier_payments_tenant_id_status_idx", table_name="supplier_payments")
    op.drop_index(
        "supplier_payments_tenant_id_supplier_id_payment_date_idx",
        table_name="supplier_payments",
    )
    op.drop_table("supplier_payments")
