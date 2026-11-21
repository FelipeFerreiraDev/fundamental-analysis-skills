from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import duckdb
import pytest

from engine.db import connect, discover_migrations, init_database, pending_migrations

BB_CNPJ = "00000000000191"


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "warehouse.duckdb"
    init_database(db_path)
    with connect(db_path) as connection:
        yield connection


def _seed_company(conn) -> str:
    run_id = conn.execute(
        "INSERT INTO ingestion_runs (provider, dataset, started_at, finished_at, status) "
        "VALUES ('cvm', 'dfp', ?, ?, 'success') RETURNING id",
        [datetime(2026, 11, 21, 10), datetime(2026, 11, 21, 10, 5)],
    ).fetchone()[0]
    file_id = conn.execute(
        "INSERT INTO source_files (ingestion_run_id, url, retrieved_at, sha256, size_bytes) "
        "VALUES (?, 'https://dados.cvm.gov.br/test.zip', ?, ?, 1) RETURNING id",
        [run_id, datetime(2026, 11, 21, 10), "0" * 64],
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO companies (cnpj, cvm_code, name, accounting_template, sector, updated_at) "
        "VALUES (?, 1023, 'BANCO DO BRASIL S.A.', 'bank', 'banking', ?)",
        [BB_CNPJ, datetime(2026, 11, 21)],
    )
    conn.execute(
        "INSERT INTO securities VALUES ('BBAS3', ?, 'ON', DATE '2000-01-01', NULL)", [BB_CNPJ]
    )
    return file_id


def _insert_filing(conn, file_id, *, doc_type, reference_date, version, received_at) -> str:
    return conn.execute(
        "INSERT INTO filings (cnpj, doc_type, reference_date, version, received_at, source_file_id)"
        " VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        [BB_CNPJ, doc_type, reference_date, version, received_at, file_id],
    ).fetchone()[0]


def _insert_fact(conn, filing_id, value: str, *, period_end=date(2024, 12, 31)):
    conn.execute(
        "INSERT INTO financial_facts (filing_id, statement, basis, account_code, account_name, "
        "period_type, period_start, period_end, value) "
        "VALUES (?, 'DRE', 'consolidated', '3.11', 'Lucro líquido', 'FY', ?, ?, ?)",
        [filing_id, date(period_end.year, 1, 1), period_end, Decimal(value)],
    )


def test_migrations_are_contiguous_and_apply_once(tmp_path):
    assert [m.version for m in discover_migrations()][0] == 1
    db_path = tmp_path / "w.duckdb"
    assert init_database(db_path)
    assert init_database(db_path) == []
    with connect(db_path) as conn:
        assert pending_migrations(conn) == []


def test_restatement_keeps_history_and_latest_view_shows_newest(conn):
    file_id = _seed_company(conn)
    dfp_2024 = _insert_filing(
        conn,
        file_id,
        doc_type="DFP",
        reference_date=date(2024, 12, 31),
        version=1,
        received_at=date(2025, 2, 20),
    )
    dfp_2025 = _insert_filing(
        conn,
        file_id,
        doc_type="DFP",
        reference_date=date(2025, 12, 31),
        version=1,
        received_at=date(2026, 2, 19),
    )
    _insert_fact(conn, dfp_2024, "100.0000")
    _insert_fact(conn, dfp_2025, "95.0000")  # FY2024 restated as the prior-year column

    history = conn.execute("SELECT count(*) FROM financial_facts").fetchone()[0]
    latest = conn.execute(
        "SELECT value, doc_type, reference_date FROM v_financial_facts_latest "
        "WHERE account_code = '3.11' AND period_end = DATE '2024-12-31'"
    ).fetchall()

    assert history == 2
    assert latest == [(Decimal("95.0000"), "DFP", date(2025, 12, 31))]


def test_company_can_be_updated_while_referenced(conn):
    file_id = _seed_company(conn)
    _insert_filing(
        conn,
        file_id,
        doc_type="ITR",
        reference_date=date(2026, 9, 30),
        version=1,
        received_at=date(2026, 11, 10),
    )
    conn.execute(
        "UPDATE companies SET sector = 'banking', updated_at = now() WHERE cnpj = ?", [BB_CNPJ]
    )


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO companies (cnpj, cvm_code, name, accounting_template, sector, updated_at) "
        "VALUES ('1', 1, 'X', 'retail', NULL, now())",
        "INSERT INTO securities VALUES ('XXXX3', '1', 'PREF', DATE '2020-01-01', NULL)",
    ],
)
def test_check_constraints_reject_invalid_categories(conn, sql):
    with pytest.raises(duckdb.ConstraintException):
        conn.execute(sql)


def test_instant_facts_have_no_period_start(conn):
    file_id = _seed_company(conn)
    filing = _insert_filing(
        conn,
        file_id,
        doc_type="DFP",
        reference_date=date(2025, 12, 31),
        version=1,
        received_at=date(2026, 2, 19),
    )
    with pytest.raises(duckdb.ConstraintException):
        conn.execute(
            "INSERT INTO financial_facts (filing_id, statement, basis, account_code, account_name,"
            " period_type, period_start, period_end, value) VALUES "
            "(?, 'BPA', 'consolidated', '1', 'Ativo total', 'INSTANT', DATE '2025-01-01', "
            "DATE '2025-12-31', 1)",
            [filing],
        )


def test_freshness_view_reports_last_success(conn):
    _seed_company(conn)
    rows = conn.execute("SELECT provider, dataset FROM v_ingestion_freshness").fetchall()
    assert rows == [("cvm", "dfp")]


def test_account_map_has_one_account_per_concept_and_layout():
    """Validity ranges of a concept (or of an account code) never overlap in a template."""
    from collections import defaultdict
    from datetime import date as _date

    from engine.db.reference import read_account_map

    def bounds(row):
        start = _date.fromisoformat(row["valid_from"]) if row["valid_from"] else _date.min
        end = _date.fromisoformat(row["valid_to"]) if row["valid_to"] else _date.max
        return start, end

    for key_fields in (("concept",), ("statement", "account_code")):
        groups = defaultdict(list)
        for row in read_account_map():
            groups[(row["accounting_template"], *(row[k] for k in key_fields))].append(bounds(row))
        for key, ranges in groups.items():
            ranges.sort()
            for (_, end), (next_start, _) in zip(ranges, ranges[1:], strict=False):
                assert end < next_start, f"overlapping validity for {key}"


def test_reference_data_is_loaded_on_init(conn):
    count = conn.execute("SELECT count(*) FROM account_map").fetchone()[0]
    assert count > 0
