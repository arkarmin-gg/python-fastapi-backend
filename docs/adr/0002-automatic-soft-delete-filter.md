# Use explicit lifecycle fields instead of automatic soft delete

> **Still current.** The foundation does **not** use a session-level
> `deleted_at IS NULL` ORM filter.

`database.dbml` may include lifecycle timestamps alongside `status`. Queries that need
“active only” must filter on `status` (and optionally `deleted_at`) in services — not via
a global `do_orm_execute` soft-delete hook.

As implemented today:

- **Organizations**: `status`, `suspended_at`, `deleted_at`
- **Users**: `status`, `locked_at`, `deleted_at` (no `suspended_at` on users)
- **Organization memberships**: `status`, `suspended_at`, and related lifecycle timestamps

We avoid a global soft-delete filter because it competes with status enums and makes
organization scoping harder to reason about.
