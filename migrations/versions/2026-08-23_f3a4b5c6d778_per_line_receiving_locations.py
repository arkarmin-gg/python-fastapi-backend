"""Move receiving location from purchase invoice header to lines

Revision ID: f3a4b5c6d778
Revises: e2f3a4b5c667
Create Date: 2026-08-23 00:00:00.000000

Each `purchase_invoice_lines` row now carries its own required
`location_id`, so a single invoice can receive into multiple locations.
Existing lines are backfilled from the header-level
`purchase_invoices.receiving_location_id`, which is then dropped.

Downgrading requires every invoice to have at least one line (the header
location is restored from the invoice's first line); delete lineless
invoices manually before downgrading if any exist.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d778"
down_revision: str | Sequence[str] | None = "e2f3a4b5c667"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "purchase_invoice_lines",
        sa.Column("location_id", sa.Uuid(), nullable=True),
    )
    op.execute("""
        UPDATE purchase_invoice_lines AS line
        SET location_id = invoice.receiving_location_id
        FROM purchase_invoices AS invoice
        WHERE line.purchase_invoice_id = invoice.id
          AND line.location_id IS NULL
    """)
    op.alter_column("purchase_invoice_lines", "location_id", nullable=False)
    op.create_foreign_key(
        "purchase_invoice_lines_location_id_fkey",
        "purchase_invoice_lines",
        "locations",
        ["location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "purchase_invoice_lines_tenant_id_location_id_idx",
        "purchase_invoice_lines",
        ["tenant_id", "location_id"],
    )

    op.drop_index(
        "purchase_invoices_tenant_id_receiving_location_id_idx",
        table_name="purchase_invoices",
    )
    op.drop_column("purchase_invoices", "receiving_location_id")


def downgrade() -> None:
    op.add_column(
        "purchase_invoices",
        sa.Column("receiving_location_id", sa.Uuid(), nullable=True),
    )
    op.execute("""
        UPDATE purchase_invoices AS invoice
        SET receiving_location_id = first_line.location_id
        FROM (
            SELECT DISTINCT ON (purchase_invoice_id)
                purchase_invoice_id,
                location_id
            FROM purchase_invoice_lines
            ORDER BY purchase_invoice_id, line_no ASC
        ) AS first_line
        WHERE invoice.id = first_line.purchase_invoice_id
    """)
    op.alter_column("purchase_invoices", "receiving_location_id", nullable=False)
    op.create_foreign_key(
        "purchase_invoices_receiving_location_id_fkey",
        "purchase_invoices",
        "locations",
        ["receiving_location_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "purchase_invoices_tenant_id_receiving_location_id_idx",
        "purchase_invoices",
        ["tenant_id", "receiving_location_id"],
    )

    op.drop_index(
        "purchase_invoice_lines_tenant_id_location_id_idx",
        table_name="purchase_invoice_lines",
    )
    op.drop_constraint(
        "purchase_invoice_lines_location_id_fkey",
        "purchase_invoice_lines",
        type_="foreignkey",
    )
    op.drop_column("purchase_invoice_lines", "location_id")
