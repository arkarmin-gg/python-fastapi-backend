"""harden customer and supplier payments

Revision ID: b9c0d1e2f334
Revises: a8b9c0d1e223
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9c0d1e2f334"
down_revision: str | None = "a8b9c0d1e223"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("customer_payments", "supplier_payments"):
        op.add_column(table, sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("reversed_by", sa.Uuid(), nullable=True))
        op.add_column(table, sa.Column("reversal_reason", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("idempotency_key", sa.String(length=255), nullable=True))
        op.create_foreign_key(
            f"{table}_reversed_by_fkey",
            table,
            "users",
            ["reversed_by"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(
            f"{table}_tenant_id_idempotency_key_key",
            table,
            ["tenant_id", "idempotency_key"],
            unique=True,
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        )


def downgrade() -> None:
    for table in ("customer_payments", "supplier_payments"):
        op.drop_index(f"{table}_tenant_id_idempotency_key_key", table_name=table)
        op.drop_constraint(f"{table}_reversed_by_fkey", table, type_="foreignkey")
        op.drop_column(table, "idempotency_key")
        op.drop_column(table, "reversal_reason")
        op.drop_column(table, "reversed_by")
        op.drop_column(table, "reversed_at")
