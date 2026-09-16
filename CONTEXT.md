# python-fastapi-backend

A FastAPI/SQLAlchemy/Postgres starter for a multi-tenant backend. It ships the
foundation layer only: global user identity, organizations, memberships, RBAC,
auth (sessions + refresh rotation), and audit logging. There is no business domain
on top of it yet — that's for whatever you build next.

Source of truth for the schema: `database.dbml`.

Core security rule:

```text
Identity ≠ Membership ≠ Authorization
```

A user may belong to multiple organizations with different roles and permissions
in each organization.

## Language

This section is a domain-language glossary: the vocabulary this codebase uses
consistently, and the terms to avoid so two people (or an agent and a person) don't end
up meaning different things by the same word. Keep it in sync as you add real domain
concepts.

### Identity

**User**:
A global authentication identity (not owned by one organization). Login uses email or
phone + password. Organization context is chosen via membership, not by storing
`organization_id` on the user row.
_Avoid_: tenant user, admin account

### Tenancy

**Organization**:
A tenant/workspace/company boundary for organization-owned resources. Organization-owned
data carries `organization_id`.
_Avoid_: tenant (legacy name in older code), workspace, account — prefer **Organization**
in APIs and docs; "tenant" may appear only as informal shorthand.

**Organization Membership**:
The join between a global user and one organization (invited/active/suspended/…). Roles
are assigned to memberships, not directly to users.
_Avoid_: user_roles, tenant membership (when meaning this entity)

### Access Control

**Permission**:
A global read-only catalog entry identified by a stable code such as `users.read`.
Permissions are granted to roles, never directly to users.
_Avoid_: grant, privilege, scope

**Role Template**:
A global platform default bundle of permissions used to seed organization roles.
_Avoid_: system role (use Role with `is_system` inside an organization)

**Role**:
An organization-scoped named bundle of permissions. May reference a role template.
_Avoid_: group, tier

**Role Permission**:
An organization-owned assignment connecting one role to one global permission.
_Avoid_: permission grant

**Membership Role**:
An organization-owned assignment connecting one membership to one role.
_Avoid_: user_roles, group membership

### Auth Credentials

**User Session**:
A global authenticated device/login session belonging to a user (not to one
organization). The same session may access multiple organizations through memberships.
_Avoid_: tenant session

**Refresh Token**:
A rotating opaque credential tied to a session. Stored only as a hash; reuse detection
should revoke the session/token family.
_Avoid_: access token (short-lived JWT is separate)

**Email Verification Token** / **Password Reset Token**:
One-time hashed tokens for account lifecycle flows.

### Observability

**Audit Log**:
An append-only record of a management or auth action. May be organization-scoped or
global (`organization_id` NULL). Captures actor user/membership snapshots and request
trace fields when available.
_Avoid_: activity log, history, change log
