# Standardize list search, filters, and sorting

Foundation list endpoints use one shared query contract on top of offset/limit
pagination:

- `search` is a case-insensitive substring search over documented text fields, where the
  endpoint exposes `search`. Blank or whitespace-only values are treated as absent.
- Filters are flat, explicit, snake_case query parameters. Endpoint-specific allowlists
  define which filters exist.
- `sort` is a single comma-separated parameter. Prefix a field with `-` for descending:
  `sort=-created_at,email`.
- Sort fields are endpoint allowlisted. Unknown, disallowed, blank, or duplicated sort
  fields return `422`.
- Services append a stable `id` tie-breaker when the requested sort does not include it,
  so offset/limit pagination has deterministic ordering.

Helpers for timestamp ranges (`created_from`, `created_to`, `updated_from`, `updated_to`)
exist in `src/query_filters.py` but **no foundation list endpoint exposes them yet**.
Multi-value repeated query filters (for example `role_ids=A&role_ids=B`) are **not** used
on GET lists; `role_ids` and `permission_ids` appear on write payloads instead.

This contract applies to organization-scoped management lists such as:

| Endpoint | Filters | `search` |
| --- | --- | --- |
| `GET /api/v1/organizations` | `status` (list is scoped to the JWT's current organization) | yes |
| `GET /api/v1/memberships` | `user_id`, `status` | no |
| `GET /api/v1/users` | `status` | yes |
| `GET /api/v1/roles` | `is_active` | yes |
| `GET /api/v1/role-permissions` | `role_id`, `permission_id` | no |
| `GET /api/v1/membership-roles` | `membership_id`, `role_id` | no |
| `GET /api/v1/audit-logs` | `action`, `entity_type`, `actor_user_id` | no |

`GET /api/v1/permissions` remains read-only reference data with deterministic ordering
because it is a bounded seeded catalog used by role forms and permission checks.

We chose this because management consoles need predictable table controls without every
endpoint inventing its own query grammar. Flat explicit filters produce clear OpenAPI
documentation and make SQL allowlists obvious. A compact `sort` string is easy for clients
to persist in URLs, while rejecting invalid fields surfaces client bugs early and prevents
accidental access to sensitive or expensive database columns.

The trade-off is that endpoint filters still need domain-specific code. That is
intentional: joins, relationship filters, and searchable fields should be explicit.
Substring search uses `ILIKE` for now; we are not adding trigram or full-text indexes until
real usage shows the need for ranked, stemmed, typo-tolerant, or high-volume search.
