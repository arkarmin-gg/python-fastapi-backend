"""initial foundation schema

Revision ID: 407f2d770c8a
Revises:
Create Date: 2026-08-06 00:00:00.000000

Creates the multi-tenant foundation: tenants, users, tenant-scoped RBAC,
audit logs, plus user refresh tokens for secure auth rotation/logout.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "407f2d770c8a"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def uuid_pk() -> sa.Column:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "tenants",
        uuid_pk(),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("legal_name", sa.String(length=250), nullable=True),
        sa.Column("currency_code", sa.String(length=3), server_default="USD", nullable=False),
        sa.Column("timezone", sa.String(length=80), server_default="UTC", nullable=False),
        sa.Column("locale", sa.String(length=20), server_default="en-US", nullable=False),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id", name="tenants_pkey"),
        sa.UniqueConstraint("code", name="tenants_code_key"),
    )
    op.create_index("tenants_code_idx", "tenants", ["code"])
    op.create_index("tenants_status_idx", "tenants", ["status"])

    op.create_table(
        "permissions",
        uuid_pk(),
        sa.Column("code", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("module", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="permissions_pkey"),
        sa.UniqueConstraint("code", name="permissions_code_key"),
    )
    op.create_index("permissions_code_idx", "permissions", ["code"])
    op.create_index("permissions_module_idx", "permissions", ["module"])

    op.create_table(
        "roles",
        uuid_pk(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="roles_tenant_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="roles_pkey"),
        sa.UniqueConstraint("tenant_id", "code", name="roles_tenant_id_code_key"),
    )
    op.create_index("roles_tenant_id_is_active_idx", "roles", ["tenant_id", "is_active"])

    op.create_table(
        "users",
        uuid_pk(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=50), server_default="active", nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_logout_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="users_tenant_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
        sa.UniqueConstraint("tenant_id", "email", name="users_tenant_id_email_key"),
    )
    op.create_index("users_tenant_id_phone_idx", "users", ["tenant_id", "phone"])
    op.create_index("users_tenant_id_status_idx", "users", ["tenant_id", "status"])

    op.create_table(
        "role_permissions",
        uuid_pk(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.Column("permission_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_id"],
            ["permissions.id"],
            name="role_permissions_permission_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="role_permissions_role_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="role_permissions_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="role_permissions_pkey"),
        sa.UniqueConstraint(
            "tenant_id",
            "role_id",
            "permission_id",
            name="role_permissions_tenant_id_role_id_permission_id_key",
        ),
    )
    op.create_index(
        "role_permissions_tenant_id_role_id_idx", "role_permissions", ["tenant_id", "role_id"]
    )
    op.create_index(
        "role_permissions_tenant_id_permission_id_idx",
        "role_permissions",
        ["tenant_id", "permission_id"],
    )

    op.create_table(
        "user_roles",
        uuid_pk(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name="user_roles_role_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="user_roles_tenant_id_fkey", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="user_roles_user_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="user_roles_pkey"),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "role_id", name="user_roles_tenant_id_user_id_role_id_key"
        ),
    )
    op.create_index("user_roles_tenant_id_user_id_idx", "user_roles", ["tenant_id", "user_id"])
    op.create_index("user_roles_tenant_id_role_id_idx", "user_roles", ["tenant_id", "role_id"])

    op.create_table(
        "audit_logs",
        uuid_pk(),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=120), nullable=False),
        sa.Column("entity_type", sa.String(length=120), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("before_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("after_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            name="audit_logs_actor_user_id_fkey",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"], name="audit_logs_tenant_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="audit_logs_pkey"),
    )
    op.create_index(
        "audit_logs_tenant_id_entity_type_entity_id_idx",
        "audit_logs",
        ["tenant_id", "entity_type", "entity_id"],
    )
    op.create_index(
        "audit_logs_tenant_id_actor_user_id_created_at_idx",
        "audit_logs",
        ["tenant_id", "actor_user_id", "created_at"],
    )
    op.create_index(
        "audit_logs_tenant_id_created_at_idx", "audit_logs", ["tenant_id", "created_at"]
    )

    op.create_table(
        "user_refresh_tokens",
        uuid_pk(),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name="user_refresh_tokens_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="user_refresh_tokens_user_id_fkey", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="user_refresh_tokens_pkey"),
        sa.UniqueConstraint("token_hash", name="user_refresh_tokens_token_hash_key"),
    )
    op.create_index("user_refresh_tokens_token_hash_idx", "user_refresh_tokens", ["token_hash"])
    op.create_index(
        "user_refresh_tokens_tenant_id_user_id_idx", "user_refresh_tokens", ["tenant_id", "user_id"]
    )
    op.create_index("user_refresh_tokens_expires_at_idx", "user_refresh_tokens", ["expires_at"])
    op.create_index(
        "user_refresh_tokens_user_id_revoked_at_idx",
        "user_refresh_tokens",
        ["user_id", "revoked_at"],
    )


def downgrade() -> None:
    op.drop_table("user_refresh_tokens")
    op.drop_table("audit_logs")
    op.drop_table("user_roles")
    op.drop_table("role_permissions")
    op.drop_table("users")
    op.drop_table("roles")
    op.drop_table("permissions")
    op.drop_table("tenants")
