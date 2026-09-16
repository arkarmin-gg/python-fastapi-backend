# Organization membership model (Identity ≠ Membership ≠ Authorization)

Accepted. Schema source: `database.dbml`.

- Users are global identities.
- Organizations are tenancy boundaries.
- `organization_memberships` connect users to organizations.
- Roles belong to organizations; permissions are a global catalog.
- `membership_roles` assign roles to memberships (not to users directly).
- Auth sessions and refresh tokens belong to users globally.
- JWT access tokens carry `user_id`, active `organization_id`, and `membership_id`.

Legacy names `tenants` / `user_roles` / tenant-scoped users are removed from the codebase.
