from scripts.clear_database import EXCLUDED_TABLES, _truncate_statement
from sqlalchemy import Column, ForeignKey, MetaData, Table
from sqlalchemy.dialects import postgresql


def test_truncate_statement_quotes_tables_and_resets_identities() -> None:
    metadata = MetaData()
    parent = Table("parents", metadata, Column("id"))
    child = Table("child records", metadata, Column("parent_id", ForeignKey("parents.id")))

    statement = _truncate_statement(postgresql.dialect(), [child, parent])

    assert statement == ('TRUNCATE TABLE "child records", parents RESTART IDENTITY CASCADE')


def test_alembic_version_is_excluded_from_clearable_data() -> None:
    assert "alembic_version" in EXCLUDED_TABLES
