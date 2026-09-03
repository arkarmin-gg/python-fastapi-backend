import argparse
import asyncio
from collections.abc import Sequence

import src.registry  # noqa: F401
from sqlalchemy import Table, text
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncSession
from src.database import SessionFactory
from src.models import Base

EXCLUDED_TABLES = {"alembic_version"}


def _clearable_tables() -> list[Table]:
    return [
        table
        for table in reversed(Base.metadata.sorted_tables)
        if table.name not in EXCLUDED_TABLES
    ]


def _truncate_statement(dialect: Dialect, tables: Sequence[Table]) -> str:
    preparer = dialect.identifier_preparer
    formatted_tables = ", ".join(preparer.format_table(table) for table in tables)
    return f"TRUNCATE TABLE {formatted_tables} RESTART IDENTITY CASCADE"


async def clear_database(db: AsyncSession, *, dry_run: bool = False) -> list[str]:
    tables = _clearable_tables()
    table_names = [table.name for table in tables]
    if not tables or dry_run:
        return table_names

    bind = db.get_bind()
    await db.execute(text(_truncate_statement(bind.dialect, tables)))
    await db.commit()
    return table_names


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clear all application data from the configured database."
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive deletion of all application table data.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print tables that would be cleared without deleting data.",
    )
    return parser.parse_args()


async def main() -> None:
    args = _parse_args()
    if not args.yes and not args.dry_run:
        raise SystemExit("Refusing to clear database without --yes. Use --dry-run to inspect.")

    async with SessionFactory() as db:
        table_names = await clear_database(db, dry_run=args.dry_run)

    action = "Would clear" if args.dry_run else "Cleared"
    print(f"{action} {len(table_names)} tables: {', '.join(table_names)}")


if __name__ == "__main__":
    asyncio.run(main())
