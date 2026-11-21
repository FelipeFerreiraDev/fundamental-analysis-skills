"""Forward-only SQL migrations stored in `engine/db/migrations/NNNN_name.sql`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib import resources

import duckdb

MIGRATIONS_PACKAGE = "engine.db.migrations"
_FILE_NAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")

_CREATE_LEDGER = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       VARCHAR NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp
)
"""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def discover_migrations() -> list[Migration]:
    migrations = []
    for entry in resources.files(MIGRATIONS_PACKAGE).iterdir():
        match = _FILE_NAME.match(entry.name)
        if match:
            migrations.append(
                Migration(int(match.group(1)), match.group(2), entry.read_text(encoding="utf-8"))
            )
    migrations.sort(key=lambda m: m.version)
    expected = list(range(1, len(migrations) + 1))
    found = [m.version for m in migrations]
    if found != expected:
        raise RuntimeError(f"migration versions must be contiguous from 0001; found {found}")
    return migrations


def _ledger_exists(conn: duckdb.DuckDBPyConnection) -> bool:
    row = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'schema_migrations'"
    ).fetchone()
    return bool(row and row[0])


def applied_versions(conn: duckdb.DuckDBPyConnection) -> set[int]:
    """Read-only safe: a database without the ledger has nothing applied."""
    if not _ledger_exists(conn):
        return set()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations").fetchall()}


def pending_migrations(conn: duckdb.DuckDBPyConnection) -> list[Migration]:
    applied = applied_versions(conn)
    return [m for m in discover_migrations() if m.version not in applied]


def migrate(conn: duckdb.DuckDBPyConnection) -> list[Migration]:
    """Apply each pending migration in its own transaction."""
    conn.execute(_CREATE_LEDGER)
    pending = pending_migrations(conn)
    for migration in pending:
        conn.execute("BEGIN TRANSACTION")
        try:
            conn.execute(migration.sql)
            conn.execute(
                "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
                [migration.version, migration.name],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return pending
