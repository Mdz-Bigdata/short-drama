"""Bringing the platform database up to the current schema, once per start.

``create_all`` still makes every table that is missing: a new table needs no migration. It cannot change a table that
exists, so anything that does is an Alembic revision under ``migrations/versions``. Create one with
``alembic -c app/platform/alembic.ini revision -m "..."`` from ``backend``.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection

from app.platform.models import Base

BASELINE_REVISION = "0001_baseline"
_SCRIPTS = Path(__file__).with_name("migrations")


def _config(connection: Connection) -> Config:
    config = Config()
    config.set_main_option("script_location", str(_SCRIPTS).replace("%", "%%"))
    config.attributes["connection"] = connection
    return config


#: Corrections to these are new rows. The database refuses anything else, whoever is asking.
_APPEND_ONLY_TABLES = ("billing_ledger", "platform_audit_events")


def _protect_financial_records(connection: Connection) -> None:
    """Here rather than in a migration, because a new database is stamped at head and never runs migrations."""
    if connection.dialect.name != "postgresql":
        return
    connection.execute(text("""
        CREATE OR REPLACE FUNCTION refuse_financial_record_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION '% records are append-only: add a correcting record instead', TG_TABLE_NAME;
        END;
        $$ LANGUAGE plpgsql
    """))
    for table in _APPEND_ONLY_TABLES:
        connection.execute(text(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}"))
        connection.execute(text(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION refuse_financial_record_change()"
        ))


def upgrade_platform_schema(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    Base.metadata.create_all(connection)
    config = _config(connection)
    if "platform_users" not in tables:
        # A new database was just created at the current schema.
        command.stamp(config, "head")
    else:
        if "alembic_version" not in tables:
            # Made before migrations existed: it is at the baseline, whatever else has run on it.
            command.stamp(config, BASELINE_REVISION)
        command.upgrade(config, "head")
    _protect_financial_records(connection)
