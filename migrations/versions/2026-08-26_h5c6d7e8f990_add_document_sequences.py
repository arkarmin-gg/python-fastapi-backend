"""add document sequences

Revision ID: h5c6d7e8f990
Revises: g4b5c6d7e889
Create Date: 2026-08-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "h5c6d7e8f990"
down_revision: str | Sequence[str] | None = "g4b5c6d7e889"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


DOCUMENT_TABLES = (
    ("sales_invoices", "sales_invoice", "SI"),
    ("purchase_invoices", "purchase_invoice", "PI"),
    ("customer_payments", "customer_payment", "CP"),
    ("supplier_payments", "supplier_payment", "SP"),
    ("stock_adjustments", "stock_adjustment", "SA"),
    ("stock_transfers", "stock_transfer", "ST"),
    ("stock_counts", "stock_count", "SC"),
    ("repack_orders", "repack_order", "RP"),
)


def upgrade() -> None:
    op.create_table(
        "document_sequences",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("document_type", sa.String(length=40), nullable=False),
        sa.Column("period", sa.String(length=6), nullable=False),
        sa.Column("last_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="document_sequences_tenant_id_fkey", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="document_sequences_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "document_type",
            "period",
            name="document_sequences_tenant_id_document_type_period_key",
        ),
    )
    op.create_index(
        "document_sequences_tenant_id_document_type_period_idx",
        "document_sequences",
        ["tenant_id", "document_type", "period"],
    )

    for table_name, document_type, prefix in DOCUMENT_TABLES:
        op.execute(
            sa.text(
                f"""
                INSERT INTO document_sequences (tenant_id, document_type, period, last_number)
                SELECT
                    tenant_id,
                    :document_type,
                    substring(document_no from 4 for 6) AS period,
                    max(substring(document_no from 11 for 6)::integer) AS last_number
                FROM {table_name}
                WHERE document_no ~ :pattern
                GROUP BY tenant_id, substring(document_no from 4 for 6)
                ON CONFLICT (tenant_id, document_type, period)
                DO UPDATE SET
                    last_number = GREATEST(
                        document_sequences.last_number,
                        EXCLUDED.last_number
                    ),
                    updated_at = now()
                """
            ).bindparams(
                document_type=document_type,
                pattern=rf"^{prefix}-[0-9]{{6}}-[0-9]{{6}}$",
            )
        )


def downgrade() -> None:
    op.drop_index("document_sequences_tenant_id_document_type_period_idx", table_name="document_sequences")
    op.drop_table("document_sequences")
