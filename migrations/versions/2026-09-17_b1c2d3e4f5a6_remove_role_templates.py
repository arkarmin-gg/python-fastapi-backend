"""remove role templates

Revision ID: b1c2d3e4f5a6
Revises: f04a0b596833
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "f04a0b596833"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "role_template_permissions" in tables:
        op.drop_table("role_template_permissions")

    if "roles" in tables:
        role_columns = {column["name"] for column in inspector.get_columns("roles")}
        if "template_id" in role_columns:
            foreign_keys = inspector.get_foreign_keys("roles")
            for foreign_key in foreign_keys:
                if foreign_key.get("constrained_columns") == ["template_id"]:
                    name = foreign_key.get("name")
                    if name:
                        op.drop_constraint(name, "roles", type_="foreignkey")
            indexes = inspector.get_indexes("roles")
            for index in indexes:
                if index.get("column_names") == ["template_id"]:
                    op.drop_index(index["name"], table_name="roles")
            op.drop_column("roles", "template_id")

    if "role_templates" in tables:
        op.drop_table("role_templates")


def downgrade() -> None:
    # The aligned baseline intentionally has no role-template domain to restore.
    pass
