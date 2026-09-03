"""add code sequences

Revision ID: i6d7e8f9a001
Revises: h5c6d7e8f990
Create Date: 2026-08-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "i6d7e8f9a001"
down_revision: str | Sequence[str] | None = "h5c6d7e8f990"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


CODE_TABLES = (
    ("employees", "employee", "EMP", "code"),
    ("locations", "location", "LOC", "code"),
    ("product_categories", "product_category", "CAT", "code"),
    ("price_levels", "price_level", "PL", "code"),
    ("suppliers", "supplier", "SUP", "code"),
    ("customers", "customer", "CUS", "code"),
    ("catalog_items", "catalog_item", "ITEM", "code"),
    ("product_variants", "product_variant", "VAR", "sku"),
)


def upgrade() -> None:
    op.create_table(
        "code_sequences",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type", sa.String(length=40), nullable=False),
        sa.Column("last_number", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="code_sequences_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="code_sequences_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "entity_type",
            name="code_sequences_tenant_id_entity_type_key",
        ),
    )
    op.create_index(
        "code_sequences_tenant_id_entity_type_idx",
        "code_sequences",
        ["tenant_id", "entity_type"],
    )

    op.add_column("catalog_items", sa.Column("code", sa.String(length=80), nullable=True))
    op.execute(
        sa.text(
            """
            WITH numbered AS (
                SELECT
                    id,
                    tenant_id,
                    row_number() OVER (PARTITION BY tenant_id ORDER BY created_at, id) AS row_no
                FROM catalog_items
                WHERE code IS NULL
            )
            UPDATE catalog_items
            SET code = 'ITEM-LEGACY-' || lpad(numbered.row_no::text, 6, '0')
            FROM numbered
            WHERE catalog_items.id = numbered.id
            """
        )
    )
    op.alter_column("catalog_items", "code", existing_type=sa.String(length=80), nullable=False)
    op.create_unique_constraint(
        "catalog_items_tenant_id_code_key",
        "catalog_items",
        ["tenant_id", "code"],
    )
    op.create_index("catalog_items_tenant_id_code_idx", "catalog_items", ["tenant_id", "code"])

    for table_name, entity_type, prefix, column_name in CODE_TABLES:
        op.execute(
            sa.text(
                f"""
                INSERT INTO code_sequences (tenant_id, entity_type, last_number)
                SELECT
                    tenant_id,
                    :entity_type,
                    max(substring({column_name} from :prefix_length)::integer) AS last_number
                FROM {table_name}
                WHERE {column_name} ~ :pattern
                GROUP BY tenant_id
                ON CONFLICT (tenant_id, entity_type)
                DO UPDATE SET
                    last_number = GREATEST(
                        code_sequences.last_number,
                        EXCLUDED.last_number
                    ),
                    updated_at = now()
                """
            ).bindparams(
                entity_type=entity_type,
                prefix_length=len(prefix) + 2,
                pattern=rf"^{prefix}-[0-9]{{6}}$",
            )
        )


def downgrade() -> None:
    op.drop_index("catalog_items_tenant_id_code_idx", table_name="catalog_items")
    op.drop_constraint(
        "catalog_items_tenant_id_code_key",
        "catalog_items",
        type_="unique",
    )
    op.drop_column("catalog_items", "code")
    op.drop_index("code_sequences_tenant_id_entity_type_idx", table_name="code_sequences")
    op.drop_table("code_sequences")
