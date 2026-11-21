"""Opening the local warehouse."""

from __future__ import annotations

from pathlib import Path

import duckdb

from engine.db.migrate import Migration, migrate
from engine.db.reference import load_reference_data
from engine.settings import get_settings


def connect(db_path: Path | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    path = db_path or get_settings().db_path
    if not read_only:
        path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def init_database(db_path: Path | None = None) -> list[Migration]:
    """Create the database if needed, apply pending migrations and reload reference data.

    Returns the migrations that were applied.
    """
    with connect(db_path) as conn:
        applied = migrate(conn)
        load_reference_data(conn)
        return applied
