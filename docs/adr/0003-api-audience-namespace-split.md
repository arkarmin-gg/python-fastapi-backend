# Keep foundation resources under one versioned API

> **Superseded.** Earlier revisions split routes into `/api/v1/admin` and `/api/v1/app`.
> The current foundation removed that audience split.

The current API keeps foundation resources directly under `/api/v1`:

- `/api/v1/auth` — `login`, `refresh`, `logout`, `me`, `me/change-password`
- `/api/v1/organizations`
- `/api/v1/memberships`
- `/api/v1/users`
- `/api/v1/roles`
- `/api/v1/permissions`
- `/api/v1/role-permissions`
- `/api/v1/membership-roles`
- `/api/v1/audit-logs`

`GET /health` lives outside the versioned prefix.

Protected routes use organization membership auth. Access tokens carry `sub` (user id),
`organization_id`, and `membership_id`; route dependencies derive organization context
from the token. Clients do not choose an organization namespace in the path.

`/users` exposes identities only through the active organization membership boundary.
Self-service global identity changes live under `/auth/me`; administrators change a
person's organization access through `/memberships`.

We use one versioned foundation API because this slice has one current authenticated
audience: organization members operating management resources. Reintroduce separate audience
namespaces only when the product has genuinely different clients with different auth,
authorization, and route stability needs.
