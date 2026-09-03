# Use tenant-scoped audit logs

> **Superseded.** Earlier revisions used an `activity_logs` table and admin-specific
> action language. The current foundation replaced that with a generic `audit_logs`
> table.

The current audit log is append-only and tenant-scoped. Rows can reference the acting
user, the affected entity type/id, the action, request metadata, and optional before/after
JSON values for management actions.

The API exposes audit logs as read-only operational evidence:

- `GET /api/v1/audit-logs`
- `GET /api/v1/audit-logs/{audit_log_id}`

Services write audit logs for key management changes such as tenant, user, role,
role-permission, and user-role updates. Auth and management actions should use the shared
audit-log service rather than each module inventing its own logging table.

The `action` field remains a string rather than a shared enum. Audit actions grow with the
application surface, and forcing every module into one migration-backed enum would make
routine instrumentation unnecessarily expensive. Domain services should keep action
strings stable because downstream audit consumers may filter on them.
