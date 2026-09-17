# Organization membership model (Identity ≠ Membership ≠ Authorization)

Accepted. Schema source: `database.dbml`.

- Users are global identities.
- Organizations are tenancy boundaries.
- `organization_memberships` connect users to organizations.
- Roles belong to organizations; permissions are a global catalog.
- `membership_roles` assign roles to memberships (not to users directly).
- Auth sessions and refresh tokens belong to users globally.
- JWT access tokens carry `sub` (user id), active `organization_id`, and `membership_id`.
- Refresh explicitly selects an organization and validates an active membership; it never
  infers tenant authority from an arbitrary membership.
- Organization administrators manage access through memberships. Global profile changes
  are self-service under `/auth/me`.

Legacy names `tenants` / `user_roles` / tenant-scoped users are removed from the codebase.
