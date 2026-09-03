"""add requires_measured_quantity and loosen measured_quantity nullability

Revision ID: e2f3a4b5c667
Revises: d1e2f3a4b556
Create Date: 2026-08-22 00:00:01.000000

`measured_quantity` on purchase/sales invoice lines is now conditionally
required (gated by `variant_units.requires_measured_quantity`), so it must
be nullable at the DB level; validation moves to the service layer.
Downgrading will fail with a NOT NULL violation if any row has
`measured_quantity IS NULL`, which is expected once this migration is live.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2f3a4b5c667"
down_revision: str | None = "d1e2f3a4b556"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "variant_units",
        sa.Column(
            "requires_measured_quantity",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )

    op.alter_column(
        "purchase_invoice_lines",
        "measured_quantity",
        existing_type=sa.Numeric(24, 8),
        nullable=True,
    )
    op.alter_column(
        "sales_invoice_lines",
        "measured_quantity",
        existing_type=sa.Numeric(24, 8),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "sales_invoice_lines",
        "measured_quantity",
        existing_type=sa.Numeric(24, 8),
        nullable=False,
    )
    op.alter_column(
        "purchase_invoice_lines",
        "measured_quantity",
        existing_type=sa.Numeric(24, 8),
        nullable=False,
    )

    op.drop_column("variant_units", "requires_measured_quantity")
