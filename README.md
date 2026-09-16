# python-fastapi-backend

FastAPI + SQLAlchemy + Postgres starter for a multi-organization backend. It ships the
generic foundation only, ready to build a real domain on top of:

- organizations (company / workspace boundary)
- global users with organization memberships
- organization-scoped RBAC with a global permission catalog and explicit role-permission /
  membership-role assignment lifecycle
- membership-aware auth with sessions and refresh-token rotation
- organization-scoped audit logs

Schema source of truth: `database.dbml`.

## Stack

Python 3.13 · uv · FastAPI · SQLAlchemy 2.0 async · asyncpg · Alembic · Pydantic v2 ·
PyJWT · argon2-cffi · ruff · pytest

## Layout

```text
src/
├── api/routers.py
├── config.py        database.py      models.py
├── dependencies.py  exceptions.py    main.py     registry.py
├── modules/
│   ├── auth/           login/logout/refresh/me, sessions, refresh tokens
│   ├── organizations/  organization records
│   ├── memberships/    organization_memberships
│   ├── users/          global user identity
│   ├── rbac/           roles, permissions, role_permissions, membership_roles,
│   │                   role_templates
│   └── audit_logs/     organization-scoped audit trail
├── pagination.py
└── query_filters.py
migrations/          foundation baseline migration
scripts/seed.py      demo organization + owner role/membership seed
scripts/clear_database.py destructive local data reset helper
tests/               auth and foundation CRUD/RBAC/audit tests
```

`src/registry.py` imports every active model module so `Base.metadata` is complete for
the app, Alembic, tests, and seed.

## Quick Start

```bash
uv sync
cp .env.example .env
createdb <your-db-name>   # match DATABASE_URL in .env
make migrate
make seed
make run
```

The seed script creates one organization, the full permission catalog, an Owner role, one
owner user, and an active membership. Defaults (override via env vars):

- `ORGANIZATION_CODE=demo` (also accepts legacy `TENANT_CODE`)
- `ORGANIZATION_NAME="Demo Organization"` (also accepts legacy `TENANT_NAME`)
- `ADMIN_EMAIL=owner@example.com`
- `ADMIN_PASSWORD=ChangeMe123!`

Log in with:

```http
POST /api/v1/auth/login
{
  "organization_code": "demo",
  "identifier": "owner@example.com",
  "password": "ChangeMe123!"
}
```

Use the returned bearer token for `/api/v1/organizations`, `/api/v1/users`,
`/api/v1/roles`, `/api/v1/permissions`, `/api/v1/role-permissions`,
`/api/v1/membership-roles`, and `/api/v1/audit-logs`.

Access tokens carry `sub` (user id), `organization_id`, and `membership_id`.

## Make Targets

| Command                      | What it does                         |
| ----------------------------- | ------------------------------------ |
| `make run`                   | API with autoreload                  |
| `make migrate`               | `alembic upgrade head`               |
| `make makemigration m="msg"` | autogenerate a migration             |
| `make downgrade`             | revert the last migration            |
| `make seed`                  | seed demo organization + owner user  |
| `make clear-db confirm=yes`  | truncate app tables, keep migrations |
| `make test`                  | run tests                            |
| `make lint` / `make format`  | ruff check + format                  |

## Conventions

- UUID primary keys with server-side `gen_random_uuid()`.
- Organization-owned tables carry `organization_id`; protected routes derive organization
  and membership context from the JWT rather than from client-supplied parameters.
- Login requires `organization_code` or `organization_id`, plus an email-or-phone
  identifier and an active membership in that organization.
- Enums are varchar-backed `StrEnum` values (see `docs/adr/0001-varchar-backed-enums.md`).
- Lifecycle uses explicit state fields like `status` and `is_active`, plus optional
  `deleted_at` timestamps where the schema defines them — not a global ORM soft-delete
  filter (see `docs/adr/0002-automatic-soft-delete-filter.md`).
- Refresh tokens are opaque, stored hashed, rotated on use (with parent/reuse tracking),
  and revoked on logout or password change. Sessions are first-class rows.
- RBAC role permissions and membership roles can be managed either through full role /
  membership replacement payloads or explicit assignment endpoints. Assignment endpoints
  validate active memberships/roles, reject duplicates, and audit assign/revoke actions.
- List endpoints share one query contract for search, filters, and sorting (see
  `docs/adr/0006-list-query-contract.md`).

## Extending this starter

This repo intentionally stops at the foundation layer. To build a real domain on top:

1. Add a new package under `src/modules/<your_module>/` following the existing shape
   (`models.py`, `schemas.py`, `service.py`, `router.py`, `exceptions.py`).
2. Register its models in `src/registry.py` and its router in `src/api/routers.py`.
3. Add its permission module name to `FOUNDATION_PERMISSION_MODULES` (or a new constant)
   in `src/modules/rbac/constants.py` if it should be permission-gated like the rest.
4. Write an Alembic migration for its tables (`make makemigration m="add <thing>"`).
5. Extend `CONTEXT.md` with the new domain vocabulary as you introduce it.

See `docs/adr/` for the architectural decisions behind the current shape, and
`FASTAPI_BEST_PRACTICES.md` for FastAPI/SQLAlchemy patterns this codebase follows.
