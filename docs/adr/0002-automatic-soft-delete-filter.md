# Use explicit lifecycle fields instead of automatic soft delete

> **Superseded.** The old starter used a `SoftDeleteMixin` and a session-level
> `deleted_at IS NULL` filter. The current foundation schema removed that behavior.

The current implementation uses explicit lifecycle fields directly:

- tenant lifecycle is represented by `tenants.status`
- user lifecycle is represented by `users.status`
- role availability is represented by `roles.is_active`
- permissions are seeded reference data
- audit logs are append-only

There is no global SQLAlchemy `do_orm_execute` filter and no shared `deleted_at` column in
the active foundation models. Deactivate/delete-style endpoints update the relevant lifecycle
field instead of hiding rows through soft delete.

We made this change because keeping starter soft-delete columns beside explicit status
fields would create two competing lifecycle systems and make tenant scoping harder to
reason about.
