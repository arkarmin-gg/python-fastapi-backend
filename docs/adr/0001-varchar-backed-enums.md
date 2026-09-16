# Store enums as VARCHAR, not native Postgres enum types

Enum-backed fields such as `organization_status` and `user_status` are modeled as Python `StrEnum`s but stored as `VARCHAR` columns (`native_enum=False`), enforcing the allowed set at the application boundary via Pydantic and the `StrEnum`, rather than creating native Postgres `ENUM` types.

We chose this because native Postgres enums are costly to evolve: `ALTER TYPE ... ADD VALUE` cannot run inside a transaction, values cannot be removed, and Alembic autogenerate does not detect enum changes. As new modules are built on this foundation, their enum sets will grow, and we want those changes to be ordinary code changes unless a table shape changes. The trade-off is that we give up DB-level type enforcement; an out-of-band `INSERT` could write an unlisted string.
