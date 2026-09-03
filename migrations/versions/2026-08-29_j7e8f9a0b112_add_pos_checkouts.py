"""add transactional pos checkouts

Revision ID: j7e8f9a0b112
Revises: i6d7e8f9a001
Create Date: 2026-08-29 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j7e8f9a0b112"
down_revision: str | Sequence[str] | None = "i6d7e8f9a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pos_checkouts",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("sales_invoice_id", sa.Uuid(), nullable=False),
        sa.Column("customer_payment_id", sa.Uuid(), nullable=True),
        sa.Column("payment_method", sa.String(length=12), nullable=True),
        sa.Column("paid_now_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("cash_tendered_amount", sa.Numeric(20, 4), nullable=True),
        sa.Column("change_due_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("charged_to_account_amount", sa.Numeric(20, 4), nullable=False),
        sa.Column("customer_balance_after", sa.Numeric(20, 4), nullable=False),
        sa.Column("available_credit_after", sa.Numeric(20, 4), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="pos_checkouts_tenant_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["sales_invoice_id"],
            ["sales_invoices.id"],
            name="pos_checkouts_sales_invoice_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_payment_id"],
            ["customer_payments.id"],
            name="pos_checkouts_customer_payment_id_fkey",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="pos_checkouts_created_by_fkey", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pos_checkouts_pkey"),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="pos_checkouts_tenant_id_idempotency_key_key"
        ),
        sa.UniqueConstraint(
            "tenant_id", "sales_invoice_id", name="pos_checkouts_tenant_id_sales_invoice_id_key"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "customer_payment_id",
            name="pos_checkouts_tenant_id_customer_payment_id_key",
        ),
    )
    op.create_index(
        "pos_checkouts_tenant_id_created_at_idx",
        "pos_checkouts",
        ["tenant_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("pos_checkouts_tenant_id_created_at_idx", table_name="pos_checkouts")
    op.drop_table("pos_checkouts")
