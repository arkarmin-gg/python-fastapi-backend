"""fix sales invoice uuid defaults

Revision ID: j1f2a3b4c556
Revises: j0e1f2a3b445
Create Date: 2026-08-08 00:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "j1f2a3b4c556"
down_revision: str | None = "j0e1f2a3b445"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE sales_invoices ALTER COLUMN id SET DEFAULT gen_random_uuid()")
    op.execute("ALTER TABLE sales_invoice_lines ALTER COLUMN id SET DEFAULT gen_random_uuid()")


def downgrade() -> None:
    op.execute("ALTER TABLE sales_invoice_lines ALTER COLUMN id DROP DEFAULT")
    op.execute("ALTER TABLE sales_invoices ALTER COLUMN id DROP DEFAULT")
