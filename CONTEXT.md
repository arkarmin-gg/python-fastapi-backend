# python-fastapi-backend

A FastAPI/SQLAlchemy/Postgres starter for a multi-tenant backend. It ships the
foundation layer only: tenant identity, tenant-scoped users, RBAC, auth, and audit
logging. There is no business domain on top of it yet — that's for whatever you build
next.

RBAC includes explicit assignment lifecycles for Role Permission and User Role rows in
addition to replacement-style role/user updates.

## Language

This section is a domain-language glossary: the vocabulary this codebase uses
consistently, and the terms to avoid so two people (or an agent and a person) don't end
up meaning different things by the same word. Keep it in sync as you add real domain
concepts — when you introduce a new entity, add a short paragraph here with its
definition and an `_Avoid_` line for near-synonyms that would blur the term.

### Tenancy

**Tenant**:
An organization or account using the system. Tenant-owned data carries `tenant_id`,
and authenticated requests derive tenant context from the JWT rather than from client
query parameters.
_Avoid_: organization, workspace, account

### People

**User**:
An authentication account inside a tenant, governed by tenant roles. Login accepts
tenant code or tenant id, plus an email-or-phone identifier and password.
_Avoid_: admin, member

### Access Control

**Role**:
A tenant-scoped named bundle of permissions assigned to users. System roles can be seeded
for baseline tenant ownership.
_Avoid_: group, tier

**Permission**:
A global read-only catalog entry identified by a stable code such as `users.read` or
`roles.update`. Permissions are granted to roles, never directly to users.
_Avoid_: grant, privilege, scope

**Role Permission**:
A tenant-owned assignment row connecting one role to one global permission. It can be
managed through role replacement payloads or explicit assign/revoke endpoints.
_Avoid_: permission grant, scope mapping

**User Role**:
A tenant-owned assignment row connecting one active user to one active role. It can be
managed through user replacement payloads or explicit assign/revoke endpoints.
_Avoid_: group membership, privilege assignment, direct permission

### Auth Credentials

**Refresh Token**:
A long-lived opaque credential held by a user, exchanged to mint new short-lived access
tokens. Stored only as a hash in `user_refresh_tokens`, rotated on refresh, and revoked on
logout or password change.
_Avoid_: session, access token

### Observability

**Audit Log**:
An append-only tenant-scoped record of a management or auth action. Audit rows reference
the acting user when one exists and may capture before/after JSON state for changed
entities.
_Avoid_: activity log, history, change log
