# FastAPI Best Practices for AI Agents

This documentation is for AI coding agents working in FastAPI projects. Same rules, restructured for fast pattern matching: version pins, Do/Don't blocks, anti-patterns, and a quick-reference table.

## Compatibility Matrix

Pin to these versions or newer. Examples in this file assume them.

| Dependency        | Minimum | Notes                                                    |
| ----------------- | ------- | -------------------------------------------------------- |
| Python            | 3.11    | Required for `StrEnum` and `X \| Y` union syntax         |
| FastAPI           | 0.115   | `Annotated[T, Depends(...)]` is the idiomatic form       |
| Pydantic          | 2.7     | v1 APIs (`json_encoders`, `.dict()`) are removed         |
| pydantic-settings | 2.4     | Lives in a separate package since Pydantic v2            |
| SQLAlchemy        | 2.0     | Use the async API (`AsyncSession`, `async_sessionmaker`) |
| Alembic           | 1.13    | Async-aware migrations                                   |
| httpx             | 0.27    | Use `ASGITransport` for in-process tests                 |
| PyJWT             | 2.9     | Use this, not the unmaintained `python-jose`             |
| ruff              | 0.6     | Replaces black, isort, autoflake                         |

> The minimums above are the floor. **python-fastapi-backend itself targets Python 3.13** and the
> examples below use 3.13-only syntax: the `type X = ...` alias statement (PEP 695) and
> inline generics (`def f[T: Bound](...)`, `class Page[ItemT]`). On 3.11/3.12 you'd fall
> back to `TypeAlias` and `TypeVar`.

## Project Structure

Organize by domain, not by file type. One package per bounded context under `src/modules/`.

```
src/
├── api/
│   └── routers.py      # Assembles v1 (auth + foundation routers)
├── modules/
│   └── {domain}/       # e.g. auth/, organizations/, rbac/
│       ├── router.py
│       ├── schemas.py
│       ├── models.py
│       ├── service.py
│       ├── exceptions.py
│       ├── dependencies.py   # optional (auth, rbac)
│       ├── config.py         # optional (auth)
│       └── constants.py      # optional (rbac)
├── config.py           # Global BaseSettings
├── models.py           # Shared ORM bases + mixins
├── schemas.py          # Shared Pydantic bases (ErrorResponse, etc.)
├── exceptions.py       # Global exceptions
├── database.py         # Async engine + session factory
├── dependencies.py     # DbSession, request context
├── pagination.py       # Page[T], paginate()
├── query_filters.py    # sort, search, optional filters
├── registry.py         # Imports all model modules for metadata
└── main.py             # FastAPI app + lifespan
```

**Cross-domain imports**: always use the explicit module path. Never `from src.modules.auth import *`.

```python
from src.modules.auth import security
from src.modules.rbac import service as rbac_service
from src.modules.rbac.constants import permission_code
```

## Async Routes

### Decision rule

| Route does this                       | Use                                                     |
| ------------------------------------- | ------------------------------------------------------- |
| `await`-able non-blocking I/O         | `async def`                                             |
| Blocking I/O (no async client exists) | `def` (sync, runs in threadpool)                        |
| Mix of both                           | `async def` + `run_in_threadpool` for the blocking part |
| CPU-bound work (>50 ms compute)       | Offload to a worker process (Celery / RQ / Arq)         |

### Do / Don't

```python
# DON'T — blocking call inside async route freezes the entire event loop
@router.get("/bad")
async def bad():
    time.sleep(10)            # blocks every request on this worker
    return {"ok": True}

# DO — sync route lets FastAPI run it in a threadpool
@router.get("/sync-ok")
def sync_ok():
    time.sleep(10)            # blocks one threadpool worker, not the loop
    return {"ok": True}

# DO — async route with awaitable sleep
@router.get("/async-ok")
async def async_ok():
    await asyncio.sleep(10)   # yields control, loop keeps serving requests
    return {"ok": True}

# DO — async route that has to call a sync library
from fastapi.concurrency import run_in_threadpool

@router.get("/wrap")
async def wrap():
    result = await run_in_threadpool(legacy_sync_client.fetch, "id")
    return result
```

### Threadpool caveats

- Default Starlette threadpool size is 40. Saturating it slows every sync route.
- Threads cost more than coroutines. Don't use sync routes "just because."

## Pydantic

### Use built-in validators

```python
from enum import StrEnum
from pydantic import AnyUrl, BaseModel, EmailStr, Field


class MusicBand(StrEnum):
    AEROSMITH = "AEROSMITH"
    QUEEN = "QUEEN"
    ACDC = "AC/DC"


class UserCreate(BaseModel):
    first_name: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    email: EmailStr
    age: int = Field(ge=18)                     # required, must be >= 18
    favorite_band: MusicBand | None = None
    website: AnyUrl | None = None
```

> **Don't** write `Field(ge=18, default=None)`. The constraint and the default contradict
> each other. Decide: required (`Field(ge=18)`) or optional (`int | None = Field(default=None, ge=18)`).

### Custom base model — modern serialization

`json_encoders` is deprecated in Pydantic v2. Use `@field_serializer` for per-field rules,
or annotate a custom type with `PlainSerializer`.

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, ConfigDict, field_serializer


class CustomModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_datetimes(self, value):
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=ZoneInfo("UTC"))
            return value.strftime("%Y-%m-%dT%H:%M:%S%z")
        return value
```

### Split BaseSettings by domain

`pydantic-settings` is its own package since Pydantic v2.

```python
# src/modules/auth/config.py
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTH_", env_file=".env", extra="ignore")

    JWT_SECRET: str = Field(min_length=32)
    JWT_ALG: str = "HS256"
    JWT_ACCESS_EXP_MINUTES: int = 15
    REFRESH_TOKEN_EXP_DAYS: int = 14


auth_settings = AuthSettings()
```

## Dependencies

### Use Annotated, not default-arg `Depends(...)`

`Annotated[T, Depends(...)]` is the idiomatic form since FastAPI 0.95 and avoids
gotchas with default values.

```python
# DO — modern Annotated form
from typing import Annotated
from fastapi import Depends

PostDep = Annotated[dict, Depends(valid_post_id)]

@router.get("/posts/{post_id}")
async def get_post(post: PostDep):
    return post

# Avoid — default-argument form (still works, but legacy)
@router.get("/posts/{post_id}")
async def get_post(post: dict = Depends(valid_post_id)):
    return post
```

### Validate inside dependencies (not just inject)

```python
async def valid_post_id(post_id: UUID4) -> dict:
    post = await service.get_by_id(post_id)
    if not post:
        raise PostNotFound()
    return post
```

### Chain dependencies for reuse

```python
async def valid_owned_post(
    post: Annotated[dict, Depends(valid_post_id)],
    token_data: Annotated[dict, Depends(parse_jwt_data)],
) -> dict:
    if post["creator_id"] != token_data["user_id"]:
        raise UserNotOwner()
    return post
```

### Rules

- Dependencies are **cached per request**. Same `Depends(x)` called 5 times in one request → `x` runs once.
- Prefer `async def` dependencies. Sync deps run in the threadpool — wasted overhead for small CPU-only checks.
- Use **the same path-variable name** across endpoints when you want to share a dependency (e.g. `profile_id` in both `/profiles/{profile_id}` and `/creators/{profile_id}`).

## Authentication — JWT

Use **`PyJWT`**, not `python-jose` (unmaintained).

```python
import jwt  # PyJWT
from jwt.exceptions import InvalidTokenError

def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALG])
    except InvalidTokenError as exc:
        raise InvalidCredentials() from exc
```

## Database — SQLAlchemy 2.0 async

Prefer SQLAlchemy 2.0's async API. `encode/databases` is in maintenance mode — don't pick it for new projects.

```python
# src/database.py
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

engine = create_async_engine(str(settings.DATABASE_URL), pool_pre_ping=True)
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_db() -> AsyncSession:
    async with SessionFactory() as session:
        yield session
```

### Naming conventions

- `lower_case_snake`
- Singular tables: `post`, `user`, `post_like`
- Group with prefix: `payment_account`, `payment_bill`
- `_at` suffix for `datetime`, `_date` suffix for `date`
- Use the same FK column name everywhere it appears (`profile_id`, not `user_id` in some tables and `profile_id` in others)

### Index naming convention

```python
from sqlalchemy import MetaData

POSTGRES_INDEXES_NAMING_CONVENTION = {
    "ix": "%(column_0_label)s_idx",
    "uq": "%(table_name)s_%(column_0_name)s_key",
    "ck": "%(table_name)s_%(constraint_name)s_check",
    "fk": "%(table_name)s_%(column_0_name)s_fkey",
    "pk": "%(table_name)s_pkey",
}
metadata = MetaData(naming_convention=POSTGRES_INDEXES_NAMING_CONVENTION)
```

### SQL-first, Pydantic-second

- Do joins, aggregation, and JSON shaping in SQL — Postgres is faster than CPython at this.
- Hydrate the result into Pydantic only for response validation, not for transformation.

## Pagination (project pattern)

List endpoints return a typed `Page[T]` envelope. The machinery lives in
`src/pagination.py` — reuse it instead of hand-rolling `limit`/`offset` per route.
See [ADR 0005](docs/adr/0005-offset-limit-pagination.md) for why offset/limit over cursors.

```python
# src/pagination.py
class PaginationParams(BaseModel):
    limit: int = DEFAULT_PAGE_SIZE
    offset: int = 0


class Page[ItemT](BaseModel):
    items: list[ItemT]
    total: int
    limit: int
    offset: int


def pagination_params(
    limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PaginationParams: ...


async def paginate[ItemT](
    db: AsyncSession,
    stmt: Select[tuple[ItemT]],
    count_stmt: Select[tuple[int]],
    pagination: PaginationParams,
) -> Page[ItemT]: ...
```

```python
# In a router: inject the params, build the two statements, hand both to paginate().
Pagination = Annotated[PaginationParams, Depends(pagination_params)]

@router.get("")
async def list_users(db: DbSession, pagination: Pagination) -> Page[UserRead]:
    stmt = select(User).order_by(User.created_at.desc())
    count_stmt = select(func.count(User.id))
    return await paginate(db, stmt, count_stmt, pagination)
```

> Build the `count_stmt` from the **same filters** as the data statement (see below), or
> `total` won't match the filtered result set. Use `get_all()` only for genuinely small,
> unbounded lists (e.g. the permission catalog).

## Dynamic filtering (project pattern)

`src/query_filters.py` provides `where_if_not_none`, `where_gte_if_not_none`, and
`where_lte_if_not_none` for optional filters — apply them to **both** the data and the
count statement so the two stay in sync.

```python
# src/query_filters.py — note the generic bound: the helper returns the SAME Select
# subtype it was given, so chaining preserves Select[tuple[AuditLog]] vs Select[tuple[int]].
type Column = ColumnElement[Any] | InstrumentedAttribute[Any]

def where_if_not_none[StmtT: Select[Any]](
    stmt: StmtT, column: Column, value: object | None
) -> StmtT:
    if value is None:
        return stmt
    return stmt.where(column == value)
```

```python
# Apply the same filters to data + count via one generic helper.
def _apply_filters[StmtT: Select[Any]](stmt: StmtT, f: AuditLogFilters) -> StmtT:
    stmt = where_if_not_none(stmt, AuditLog.actor_user_id, f.actor_user_id)
    stmt = where_if_not_none(stmt, AuditLog.action, f.action)
    return stmt

data = _apply_filters(select(AuditLog), filters)
count = _apply_filters(select(func.count(AuditLog.id)), filters)
```

> **Why the `Column` alias accepts `InstrumentedAttribute`**: a mapped attribute
> (`AuditLog.actor_user_id`) is typed `InstrumentedAttribute[...]`, which type checkers do not
> treat as a `ColumnElement` even though it is one at runtime. Widening the parameter to
> the union keeps the helpers callable on model columns without `# type: ignore`.

## List search, filters, and sorting (project pattern)

Foundation list endpoints follow [ADR 0006](docs/adr/0006-list-query-contract.md):

- Use `search` on endpoints that expose it (organizations, users, roles) for case-insensitive substring search.
- Treat blank `search` and blank optional string filters as absent.
- Use flat explicit filters per endpoint (`status`, `user_id`, `is_active`, `role_id`, etc.).
- `created_from` / `updated_*` helpers exist in `query_filters.py` but no list route exposes them yet.
- `role_ids` on write bodies (`UserCreate`, role payloads) is not a repeated GET query filter.
- Use one comma-separated `sort` string; prefix a field with `-` for descending.
- Reject unknown, blank, or duplicate sort fields with `422`.
- Append `id` as a stable tie-breaker internally when the requested sort omits it.

Examples:

```text
GET /api/v1/users?search=owner@example&status=active&sort=-created_at,name
GET /api/v1/roles?search=owner&is_active=true&sort=code
GET /api/v1/audit-logs?action=auth.login&sort=-created_at
GET /api/v1/memberships?user_id=<uuid>&status=active
```

Manual QA checklist when changing this contract:

- `GET /api/v1/users?search=<known-email-fragment>` returns a filtered `Page`.
- `GET /api/v1/users?search=%20%20` behaves like no search.
- `GET /api/v1/roles?sort=missing_field` returns `422`.
- `GET /api/v1/organizations` returns only the JWT's current organization (not a global directory).
- `GET /api/v1/permissions` returns the full catalog (not paginated).

## API audience split (project pattern)

There is a single authenticated audience under `/api/v1`. `src/api/routers.py` mounts
`auth_router` and `foundation_router` (organizations, memberships, users, rbac, audit_logs)
under `settings.API_V1_PREFIX`. There is no `/admin` or `/app` namespace. See
[ADR 0003](docs/adr/0003-api-audience-namespace-split.md) (superseded to a single versioned surface).

```python
foundation_router = APIRouter()
foundation_router.include_router(organizations_router)
foundation_router.include_router(memberships_router)
foundation_router.include_router(users_router)
foundation_router.include_router(rbac_router)
foundation_router.include_router(audit_logs_router)

v1 = APIRouter(prefix=settings.API_V1_PREFIX)
v1.include_router(auth_router)
v1.include_router(foundation_router)
```

## Background work — BackgroundTasks vs Celery

| Use BackgroundTasks when…                | Use Celery / Arq / RQ when…                  |
| ---------------------------------------- | -------------------------------------------- |
| Task is < 1 second                       | Task takes seconds to minutes                |
| Failure can be silently dropped          | You need retries, dead-letter, or visibility |
| Task is in-process (send email, log row) | Task is CPU-heavy or needs a separate pool   |
| You don't need scheduling                | You need cron, ETA, or rate limiting         |

```python
from fastapi import BackgroundTasks

@router.post("/signup")
async def signup(data: SignupIn, bg: BackgroundTasks):
    user = await service.create_user(data)
    bg.add_task(send_welcome_email, user.email)   # fire-and-forget, in-process
    return user
```

> BackgroundTasks run **after the response is sent, in the same worker process**. If the
> worker dies, the task is lost. There is no retry. Don't use them for anything you'd
> page on.

## Testing

### Async client from day one

```python
import pytest
from httpx import AsyncClient, ASGITransport

from src.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_post(client: AsyncClient):
    resp = await client.post("/posts", json={"title": "hi"})
    assert resp.status_code == 201
```

> **Don't** use `async_asgi_testclient` — it's unmaintained. The example above (httpx +
> `ASGITransport`) is the supported path.

### Override dependencies in tests

Don't monkeypatch internals. Use FastAPI's built-in `dependency_overrides`.

```python
from src.modules.auth.dependencies import get_current_user_context
from src.main import app


def fake_user():
    return {"user_id": "00000000-0000-0000-0000-000000000001"}


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[parse_jwt_data] = fake_user
    yield
    app.dependency_overrides.clear()
```

## Migrations (Alembic)

- Migrations must be static and reversible.
- Use the async template: `alembic init -t async migrations`
- Descriptive filenames:
  ```ini
  # alembic.ini
  file_template = %%(year)d-%%(month).2d-%%(day).2d_%%(slug)s
  ```
  → `2026-04-14_add_post_content_idx.py`

## API documentation

### Hide docs outside selected envs

```python
from fastapi import FastAPI
from src.config import settings

SHOW_DOCS_IN = {"local", "staging"}
app_kwargs = {"title": "My API"}
if settings.ENVIRONMENT not in SHOW_DOCS_IN:
    app_kwargs["openapi_url"] = None    # disables /docs and /redoc

app = FastAPI(**app_kwargs)
```

### Document endpoints fully

```python
from fastapi import APIRouter, status

router = APIRouter()


@router.post(
    "/items",
    response_model=ItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an item",
    description="Creates an item owned by the authenticated user.",
    tags=["items"],
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse, "description": "Validation error"},
        status.HTTP_409_CONFLICT:    {"model": ErrorResponse, "description": "Slug already exists"},
    },
)
async def create_item(payload: ItemCreate) -> ItemResponse: ...
```

## Linting

```shell
ruff check --fix src
ruff format src
```

Add to a pre-commit hook or run in CI. Ruff replaces black + isort + autoflake + most of flake8.

---

## Anti-patterns — common AI-agent mistakes

If you're an agent reviewing a diff, check for these. Each is a real failure mode I've
seen agents introduce.

| Anti-pattern                                                                       | Why it's wrong                                       | Fix                                                                                                                   |
| ---------------------------------------------------------------------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| `requests.get(...)` inside `async def`                                             | Blocks the event loop. `requests` is sync.           | Use `httpx.AsyncClient` or `await run_in_threadpool(requests.get, ...)`.                                              |
| `time.sleep` / `open()` / sync DB driver inside `async def`                        | Same — blocks the loop.                              | Use the async equivalent (`asyncio.sleep`, `aiofiles`, async driver).                                                 |
| `from jose import jwt`                                                             | `python-jose` is unmaintained.                       | `import jwt` (PyJWT).                                                                                                 |
| `from async_asgi_testclient import TestClient`                                     | Unmaintained.                                        | `httpx.AsyncClient` + `ASGITransport`.                                                                                |
| `model_config = ConfigDict(json_encoders={...})`                                   | Deprecated in Pydantic v2.                           | `@field_serializer` or `Annotated[T, PlainSerializer(...)]`.                                                          |
| `Field(ge=18, default=None)`                                                       | Constraint contradicts the default.                  | Pick required or optional, not both.                                                                                  |
| `def get_user(id: int = Depends(...))` (default-arg form)                          | Legacy; gotchas with default values.                 | `user: Annotated[User, Depends(...)]`.                                                                                |
| Catching `Exception` around a route's body                                         | Hides bugs and turns 500s into silent 200s.          | Catch the specific exception class; raise `HTTPException` with a meaningful status.                                   |
| `BackgroundTasks` for anything you'd page on                                       | No retry, dies with the worker.                      | Use Celery / Arq / RQ.                                                                                                |
| Calling a sync ORM session inside `async def`                                      | Blocks the loop, may deadlock the pool.              | Use `AsyncSession`.                                                                                                   |
| Returning a Pydantic model and _also_ setting `response_model=` to that same class | Model gets constructed twice (validate + serialize). | Either return a `dict`/ORM row and let `response_model` validate, or drop `response_model` and trust the return type. |
| Importing across domains via deep paths (`from src.modules.auth.service import ...` from unrelated modules) | Tight coupling, hard to refactor.                    | `from src.modules.auth import service as auth_service`.                                                               |
| Reusing one `BaseSettings` for the whole app                                       | Hard to reason about, every domain reads every var.  | One `BaseSettings` per domain.                                                                                        |
| Mocking the database in integration tests                                          | Mock/prod divergence eventually fires in prod.       | Use a real DB (testcontainers, ephemeral schema) and `dependency_overrides` for auth/external services.               |

## Quick reference

| Scenario                          | Solution                                       |
| --------------------------------- | ---------------------------------------------- |
| Non-blocking I/O                  | `async def` route with `await`                 |
| Blocking I/O (no async client)    | `def` route (sync, runs in threadpool)         |
| Sync library inside async route   | `await run_in_threadpool(fn, *args)`           |
| CPU-intensive work                | Celery / Arq / RQ worker process               |
| Request validation against DB     | Dependency that loads + validates + returns    |
| Reuse validation across routes    | Chain dependencies                             |
| Inject dependency in modern style | `Annotated[T, Depends(...)]`                   |
| Per-request dep caching           | Default behavior — same `Depends(x)` runs once |
| Per-domain config                 | One `BaseSettings` subclass per domain         |
| Custom datetime serialization     | `@field_serializer`                            |
| Fire-and-forget short task        | `BackgroundTasks`                              |
| Reliable / scheduled / heavy task | Celery / Arq / RQ                              |
| JWT decode                        | `PyJWT` (`import jwt`)                         |
| Async DB                          | SQLAlchemy 2.0 async (`AsyncSession`)          |
| HTTP test client                  | `httpx.AsyncClient` + `ASGITransport`          |
| Swap dep in tests                 | `app.dependency_overrides[dep] = fake`         |
| Lint + format                     | `ruff check --fix` + `ruff format`             |
