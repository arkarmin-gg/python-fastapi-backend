"""Add sales invoice line locations (per-line stock splits)

Revision ID: g4b5c6d7e889
Revises: f3a4b5c6d778
Create Date: 2026-08-23 01:00:00.000000

Each inventory-tracked `sales_invoice_lines` row is now fulfilled from one
or more explicit location splits (`sales_invoice_line_locations`), letting a
single customer-facing line draw stock from multiple locations. Existing
lines are backfilled with a single split covering their full quantity from
their resolved source location (`source_location_id`, falling back to the
invoice's POS location).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "g4b5c6d7e889"
down_revision: str | Sequence[str] | None = "f3a4b5c6d778"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sales_invoice_line_locations",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "sales_invoice_line_id",
            sa.Uuid(),
            sa.ForeignKey("sales_invoice_lines.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "location_id",
            sa.Uuid(),
            sa.ForeignKey("locations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("quantity", sa.Numeric(24, 8), nullable=False),
        sa.Column("quantity_base", sa.Numeric(24, 8), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "sales_invoice_line_id",
            "location_id",
            name="sales_invoice_line_locations_line_location_key",
        ),
    )
    op.create_index(
        "sinv_line_locations_tenant_id_line_id_idx",
        "sales_invoice_line_locations",
        ["tenant_id", "sales_invoice_line_id"],
    )
    op.create_index(
        "sinv_line_locations_tenant_id_location_id_idx",
        "sales_invoice_line_locations",
        ["tenant_id", "location_id"],
    )

    op.execute("""
        INSERT INTO sales_invoice_line_locations
            (tenant_id, sales_invoice_line_id, location_id, quantity, quantity_base)
        SELECT
            line.tenant_id,
            line.id,
            COALESCE(line.source_location_id, invoice.location_id),
            line.quantity,
            line.quantity_base
        FROM sales_invoice_lines AS line
        JOIN sales_invoices AS invoice ON invoice.id = line.sales_invoice_id
        JOIN product_variants AS variant ON variant.id = line.product_variant_id
        WHERE variant.track_inventory
    """)


def downgrade() -> None:
    op.drop_index(
        "sinv_line_locations_tenant_id_location_id_idx",
        table_name="sales_invoice_line_locations",
    )
    op.drop_index(
        "sinv_line_locations_tenant_id_line_id_idx",
        table_name="sales_invoice_line_locations",
    )
    op.drop_table("sales_invoice_line_locations")
