# python-fastapi-backend

FastAPI + SQLAlchemy + Postgres starter for a multi-tenant backend. It ships the
generic foundation only, ready to build a real domain on top of:

- tenants
- tenant-scoped users
- tenant-scoped RBAC with a global permission catalog and explicit role-permission /
  user-role assignment lifecycle
- tenant user auth with refresh-token rotation
- tenant-scoped audit logs

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
│   ├── auth/        login/logout/refresh/me and user_refresh_tokens
│   ├── tenants/     tenant/company records
│   ├── users/       user accounts and user_roles
│   ├── rbac/        roles, permissions, role_permissions, user_role assignments
│   └── audit_logs/  tenant-scoped audit trail
├── pagination.py
└── query_filters.py
migrations/          one foundation baseline migration
scripts/seed.py      demo tenant + owner role/user seed
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

The seed script creates one tenant, the full permission catalog, an Owner role, and one
owner user. Defaults (override via env vars):

- `TENANT_CODE=demo`
- `TENANT_NAME="Demo Tenant"`
- `ADMIN_EMAIL=owner@example.com`
- `ADMIN_PASSWORD=ChangeMe123!`

Log in with:

```http
POST /api/v1/auth/login
{
  "tenant_code": "demo",
  "identifier": "owner@example.com",
  "password": "ChangeMe123!"
}
```

Use the returned bearer token for `/api/v1/tenants`, `/api/v1/users`, `/api/v1/roles`,
`/api/v1/permissions`, `/api/v1/role-permissions`, `/api/v1/user-roles`, and
`/api/v1/audit-logs`.

## Make Targets

| Command                      | What it does                         |
| ----------------------------- | ------------------------------------ |
| `make run`                   | API with autoreload                  |
| `make migrate`               | `alembic upgrade head`               |
| `make makemigration m="msg"` | autogenerate a migration             |
| `make downgrade`             | revert the last migration            |
| `make seed`                  | seed demo tenant + owner user        |
| `make clear-db confirm=yes`  | truncate app tables, keep migrations |
| `make test`                  | run tests                            |
| `make lint` / `make format`  | ruff check + format                  |

## Conventions

- UUID primary keys with server-side `gen_random_uuid()`.
- Tenant-owned tables carry `tenant_id`; protected routes derive tenant context from
  the JWT rather than from client-supplied parameters.
- Login requires `tenant_code` or `tenant_id`, plus an email-or-phone identifier.
- Enums are varchar-backed `StrEnum` values (see `docs/adr/0001-varchar-backed-enums.md`).
- Lifecycle uses explicit state fields like `status` and `is_active`, not soft delete
  (see `docs/adr/0002-automatic-soft-delete-filter.md`).
- Refresh tokens are opaque, stored hashed, rotated on use, and revoked on logout or
  password change.
- RBAC role permissions and user roles can be managed either through full role/user
  replacement payloads or explicit assignment endpoints. Assignment endpoints validate
  active tenant-owned users/roles, reject duplicates, and audit assign/revoke actions.
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
