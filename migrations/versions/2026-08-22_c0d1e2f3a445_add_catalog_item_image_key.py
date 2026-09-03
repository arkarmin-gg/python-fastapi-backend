"""add catalog item image key

Revision ID: c0d1e2f3a445
Revises: b9c0d1e2f334
Create Date: 2026-08-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c0d1e2f3a445"
down_revision: str | None = "b9c0d1e2f334"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("catalog_items", sa.Column("image_key", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("catalog_items", "image_key")
