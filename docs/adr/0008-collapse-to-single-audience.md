# Replace the admin starter with the POS foundation

> Supersedes the old admin-starter decisions in
> [ADR 0002](0002-automatic-soft-delete-filter.md),
> [ADR 0003](0003-api-audience-namespace-split.md), and
> [ADR 0007](0007-unified-activity-log.md).

The codebase now treats `POS_ERD.dbml` as the source of truth for its foundation slice.
This was a hard replacement of the previous admin starter, not a compatibility layer.

Removed starter concepts:

- `admins`
- `auth_admin`
- starter RBAC modules
- generic `settings`
- `activity_logs`
- global soft-delete filtering
- `/api/v1/admin/...` and `/api/v1/auth/admin/...` routes

Implemented POS foundation concepts:

- `tenants`
- `employees`
- `users`
- tenant-scoped `roles`
- global `permissions`
- `role_permissions`
- `user_roles`
- tenant-scoped `audit_logs`
- `user_refresh_tokens` as auth infrastructure outside the business ERD

Protected APIs derive tenant context from the access token. Login accepts `tenant_code` or
`tenant_id` with an email-or-phone identifier and password. Access tokens carry `user_id`
and `tenant_id`; refresh tokens are opaque, hashed, rotated on refresh, and revoked on
logout or password change.

The initial Alembic baseline was replaced because this is still early-development schema
work. Existing local databases stamped with the old baseline revision should be recreated
or reset before running the new baseline.

The trade-off is intentional breakage for any old admin-starter clients or local data. That
keeps the foundation honest: the code, migration, seed, tests, Bruno collection, and docs
now describe one system instead of preserving two incompatible histories.
