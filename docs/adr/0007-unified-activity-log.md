# Audit logs (organization-scoped or global)

> **Superseded.** Earlier revisions used an `activity_logs` table and admin-specific
> action language. The current foundation replaced that with a generic `audit_logs`
> table.

The current audit log is append-only. Rows may be organization-scoped (`organization_id`
set) or global (`organization_id` NULL), for example when logging auth events that are not
tied to one organization. Rows can reference the acting user and membership, preserve
actor snapshots, identify the affected entity type/id, and capture request correlation,
IP address, user agent, and optional before/after JSON values. PostgreSQL triggers reject
updates and deletes so append-only behavior does not depend only on application policy.

The API exposes audit logs as read-only operational evidence:

- `GET /api/v1/audit-logs`
- `GET /api/v1/audit-logs/{audit_log_id}`

Services write audit logs for authentication and key management changes such as
organization, membership, user, role, role-permission, and membership-role updates. Auth
and management actions use the shared audit-log service rather than each module inventing
its own logging table.

The `action` field remains a string rather than a shared enum. Audit actions grow with the
application surface, and forcing every module into one migration-backed enum would make
routine instrumentation unnecessarily expensive. Domain services should keep action
strings stable because downstream audit consumers may filter on them.
