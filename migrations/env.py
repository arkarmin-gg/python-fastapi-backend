import asyncio
import os
import re
from logging.config import fileConfig

import src.registry  # noqa: F401  -- populates Base.metadata with every model
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from src.config import settings
from src.models import Base

config = context.config
config.set_main_option("sqlalchemy.url", str(settings.DATABASE_URL))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
_schema = os.environ.get("ALEMBIC_SCHEMA")
if _schema is not None and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", _schema) is None:
    raise ValueError("ALEMBIC_SCHEMA must be a valid unquoted PostgreSQL identifier")


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    return not (type_ == "table" and name == "alembic_version")


def run_migrations_offline() -> None:
    context.configure(
        url=str(settings.DATABASE_URL),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        version_table_schema=_schema,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        version_table_schema=_schema,
        include_name=include_name,
    )
    with context.begin_transaction():
        if _schema is not None:
            connection.exec_driver_sql(f'SET search_path TO "{_schema}"')
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
