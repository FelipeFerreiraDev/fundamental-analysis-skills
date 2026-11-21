"""Loads versioned reference data (engine/reference/) into the warehouse.

Reference tables are derived from files in git, so they are replaced on every load. They
are not facts: changing a mapping changes how facts are read, never the facts themselves.
"""

from __future__ import annotations

import csv
from importlib import resources

import duckdb
import yaml

REFERENCE_PACKAGE = "engine.reference"


def read_account_map() -> list[dict[str, str]]:
    text = resources.files(REFERENCE_PACKAGE).joinpath("account_map.csv").read_text("utf-8")
    return list(csv.DictReader(text.splitlines()))


def read_cvm_sector_map() -> dict[str, str]:
    text = resources.files(REFERENCE_PACKAGE).joinpath("cvm_sectors.yaml").read_text("utf-8")
    return {str(key): str(value) for key, value in (yaml.safe_load(text) or {}).items()}


def load_reference_data(conn: duckdb.DuckDBPyConnection) -> int:
    """Replace account_map with the versioned file. Returns the number of rows loaded."""
    rows = read_account_map()
    conn.execute("BEGIN TRANSACTION")
    try:
        conn.execute("DELETE FROM account_map")
        conn.executemany(
            "INSERT INTO account_map (accounting_template, statement, account_code, concept, "
            "sign, valid_from, valid_to, notes) "
            "VALUES (?, ?, ?, ?, ?, coalesce(?, DATE '1900-01-01'), ?, ?)",
            [
                [
                    row["accounting_template"],
                    row["statement"],
                    row["account_code"],
                    row["concept"],
                    int(row["sign"]),
                    row["valid_from"] or None,
                    row["valid_to"] or None,
                    row["notes"] or None,
                ]
                for row in rows
            ],
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return len(rows)
