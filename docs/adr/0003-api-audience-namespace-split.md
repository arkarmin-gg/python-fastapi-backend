# Keep POS foundation resources under one versioned API

> **Superseded.** Earlier revisions split routes into `/api/v1/admin` and `/api/v1/app`.
> The POS foundation refactor removed that audience split.

The current API keeps foundation resources directly under `/api/v1`:

- `/api/v1/auth`
- `/api/v1/tenants`
- `/api/v1/employees`
- `/api/v1/users`
- `/api/v1/roles`
- `/api/v1/permissions`
- `/api/v1/audit-logs`

Protected routes use tenant-scoped user auth. Access tokens carry `user_id` and
`tenant_id`; route dependencies derive tenant context from the token. Clients do not
choose a tenant namespace in the path.

We use one versioned foundation API because this slice has one current authenticated
audience: tenant users operating management resources. Reintroduce separate audience
namespaces only when the product has genuinely different clients with different auth,
authorization, and route stability needs.
