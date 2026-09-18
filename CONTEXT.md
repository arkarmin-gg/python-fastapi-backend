# python-fastapi-backend

A FastAPI/SQLAlchemy/Postgres starter for a multi-organization backend. It ships the
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
are assigned to memberships, not directly to users. Organization administrators manage
access by inviting, activating, suspending, or removing memberships; they do not mutate
the member's global identity.
_Avoid_: user_roles, tenant membership (when meaning this entity)

### Access Control

**Permission**:
A global read-only catalog entry identified by a stable code such as `users.read`.
Permissions are granted to roles, never directly to users.
_Avoid_: grant, privilege, scope

**Role**:
An organization-scoped named bundle of permissions.
_Avoid_: group, tier

**Role Permission**:
An organization-owned assignment connecting one role to one global permission.
_Avoid_: permission grant

**Membership Role**:
An organization-owned assignment connecting one membership to one role.
_Avoid_: user_roles, group membership

**Foundation permission modules**:
Seeded catalog modules: `organizations`, `users`, `memberships`, `roles`, `permissions`,
`audit_logs`. Standard CRUD codes use `{module}.{create|read|update|delete}`; memberships
also expose `memberships.invite` and `memberships.remove`.

**Role Permission API** / **Membership Role API**:
Explicit assignment endpoints at `/api/v1/role-permissions` and `/api/v1/membership-roles`
(in addition to `permission_ids` / `role_ids` on some write payloads).

### Auth Credentials

**User Session**:
A global authenticated device/login session belonging to a user (not to one
organization). The same session may access multiple organizations through memberships.
_Avoid_: tenant session

**Refresh Token**:
A rotating opaque credential tied to a session. Stored only as a hash; reuse detection
revokes the session/token family. Each refresh selects an organization and proves the user
still has an active membership there; a rotated token cannot outlive its session.
_Avoid_: access token (short-lived JWT is separate)

**Access Token (JWT)**:
Short-lived bearer token. Claims include `sub` (user id), `organization_id`, and
`membership_id` for the organization selected at login or refresh.
_Avoid_: storing organization on the user row as the sole context

**Email Verification Token** / **Password Reset Token**:
One-time hashed tokens for account lifecycle flows. **Schema-only today** (tables and ORM
models exist; no issue or consume API routes yet).

### Observability

**Request Context**:
Per-request metadata captured from the HTTP layer: optional `x-request-id` and
`x-trace-id` headers, client IP, and user agent. Fed into audit rows when services call
`record_audit_log`.
_Avoid_: assuming correlation fields are always present

**Actor Type**:
Who performed an audited action: `user`, `system`, `service`, or `api_key` (see
`ActorType` in `src/foundation_enums.py`).

**Audit Log**:
An append-only record of a management or auth action. May be organization-scoped or
global (`organization_id` NULL). Captures actor user/membership snapshots and request
trace fields when available.
_Avoid_: activity log, history, change log
