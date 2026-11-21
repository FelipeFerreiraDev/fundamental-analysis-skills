"""`skillsinvest sync <TICKER>`: loads a company's CVM data into the local warehouse."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from uuid import UUID

import duckdb

from engine.config import SyncConfig
from engine.ingest import cvm
from engine.ingest.http import Fetcher, RemoteFile, RemoteMetadata
from engine.ingest.manifest import already_ingested, finish_run, record_source_file, start_run


class TickerNotFoundError(LookupError):
    pass


@dataclass
class SyncReport:
    ticker: str
    cnpj: str = ""
    name: str = ""
    accounting_template: str = ""
    sector: str | None = None
    files_loaded: list[str] = field(default_factory=list)
    files_unchanged: list[str] = field(default_factory=list)
    filings_added: int = 0
    facts_added: int = 0
    warnings: list[str] = field(default_factory=list)


@contextmanager
def ingestion_run(conn: duckdb.DuckDBPyConnection, provider: str, dataset: str) -> Iterator[UUID]:
    run_id = start_run(conn, provider, dataset)
    try:
        yield run_id
    except Exception as exc:
        finish_run(conn, run_id, error=f"{type(exc).__name__}: {exc}")
        raise
    finish_run(conn, run_id)


@contextmanager
def transaction(conn: duckdb.DuckDBPyConnection) -> Iterator[None]:
    conn.execute("BEGIN TRANSACTION")
    try:
        yield
    except Exception:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _years(today: date, count: int) -> list[int]:
    return list(range(today.year - count + 1, today.year + 1))


def sync_company(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    *,
    cvm_base_url: str,
    config: SyncConfig,
    fetcher: Fetcher,
    sector_map: dict[str, str],
    sector_overrides: dict[str, str],
    today: date | None = None,
) -> SyncReport:
    today = today or date.today()
    ticker = ticker.strip().upper()
    report = SyncReport(ticker=ticker)

    securities, fca_file = _resolve_securities(conn, ticker, cvm_base_url, fetcher, today)
    cnpj = next(s.cnpj for s in securities if s.ticker == ticker)
    report.cnpj = cnpj

    with ingestion_run(conn, "cvm", "cad") as run_id:
        cad = fetcher.fetch(f"{cvm_base_url}/CAD/DADOS/cad_cia_aberta.csv")
        registry = cvm.parse_registry(cad.path, cnpj)
        if registry is None:
            raise TickerNotFoundError(f"CNPJ {cvm.format_cnpj(cnpj)} não está no cadastro da CVM")
        _record_once(conn, run_id, cad, cnpj, rows=1)
    with ingestion_run(conn, "cvm", "fca") as run_id:
        _record_once(conn, run_id, fca_file, cnpj, rows=len(securities))

    report.name = registry.name
    report.sector = sector_overrides.get(ticker) or cvm.sector_profile(
        registry.cvm_sector, sector_map
    )
    if report.sector is None:
        report.warnings.append(
            f"setor da CVM {registry.cvm_sector!r} sem perfil setorial: "
            "defina o perfil em config/sector_overrides.yaml"
        )

    for doc_type, years in (
        ("DFP", _years(today, config.history_years)),
        ("ITR", _years(today, config.quarterly_years)),
    ):
        with ingestion_run(conn, "cvm", doc_type.lower()) as run_id:
            pending = _download_documents(
                conn, doc_type, years, cnpj, cvm_base_url, fetcher, report
            )
            if doc_type == "DFP":
                template = cvm.detect_accounting_template(
                    fact for _, docs in pending for fact in docs.facts
                ) or _stored_template(conn, cnpj)
                if template is None:
                    raise cvm.CvmFormatError(
                        f"não foi possível identificar o template contábil de {ticker}"
                    )
                report.accounting_template = template
                _upsert_company(conn, registry, template, report.sector, securities)
            for remote, docs in pending:
                with transaction(conn):
                    source_file_id = record_source_file(
                        conn, run_id, remote, rows_loaded=len(docs.facts), cnpjs=[cnpj]
                    )
                    filings, facts = _store_documents(conn, cnpj, docs, source_file_id)
                report.filings_added += filings
                report.facts_added += facts
    return report


def _resolve_securities(
    conn: duckdb.DuckDBPyConnection, ticker: str, base: str, fetcher: Fetcher, today: date
) -> tuple[list[cvm.ListedSecurity], RemoteFile]:
    for year in (today.year, today.year - 1):
        url = f"{base}/DOC/FCA/DADOS/fca_cia_aberta_{year}.zip"
        if fetcher.metadata(url) is None:
            continue
        remote = fetcher.fetch(url)
        listed = cvm.parse_securities(remote.path)
        match = next((s for s in listed if s.ticker == ticker), None)
        if match is not None:
            return [s for s in listed if s.cnpj == match.cnpj], remote
    raise TickerNotFoundError(f"ticker {ticker} não encontrado no FCA da CVM")


def _record_once(
    conn: duckdb.DuckDBPyConnection, run_id: UUID, remote: RemoteFile, cnpj: str, *, rows: int
) -> None:
    meta = RemoteMetadata(remote.url, remote.etag, remote.last_modified)
    if not already_ingested(conn, meta, cnpj):
        record_source_file(conn, run_id, remote, rows_loaded=rows, cnpjs=[cnpj])


def _download_documents(
    conn: duckdb.DuckDBPyConnection,
    doc_type: str,
    years: list[int],
    cnpj: str,
    base: str,
    fetcher: Fetcher,
    report: SyncReport,
) -> list[tuple[RemoteFile, cvm.CompanyDocuments]]:
    folder, prefix = doc_type, doc_type.lower()
    pending = []
    for year in years:
        url = f"{base}/DOC/{folder}/DADOS/{prefix}_cia_aberta_{year}.zip"
        meta = fetcher.metadata(url)
        if meta is None:
            continue
        name = url.rsplit("/", 1)[-1]
        if already_ingested(conn, meta, cnpj):
            report.files_unchanged.append(name)
            continue
        remote = fetcher.fetch(url)
        pending.append((remote, cvm.parse_documents(remote.path, doc_type, cnpj)))
        report.files_loaded.append(name)
    return pending


def _stored_template(conn: duckdb.DuckDBPyConnection, cnpj: str) -> str | None:
    row = conn.execute(
        "SELECT accounting_template FROM companies WHERE cnpj = ?", [cnpj]
    ).fetchone()
    return row[0] if row else None


def _upsert_company(
    conn: duckdb.DuckDBPyConnection,
    registry: cvm.CompanyRegistry,
    template: str,
    sector: str | None,
    securities: list[cvm.ListedSecurity],
) -> None:
    conn.execute(
        """
        INSERT INTO companies (cnpj, cvm_code, name, accounting_template, sector, updated_at,
                               cvm_sector, control_type, registration_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (cnpj) DO UPDATE SET
            cvm_code = excluded.cvm_code,
            name = excluded.name,
            accounting_template = excluded.accounting_template,
            sector = excluded.sector,
            updated_at = excluded.updated_at,
            cvm_sector = excluded.cvm_sector,
            control_type = excluded.control_type,
            registration_status = excluded.registration_status
        """,
        [
            registry.cnpj,
            registry.cvm_code,
            registry.name,
            template,
            sector,
            datetime.now(),
            registry.cvm_sector,
            registry.control_type,
            registry.registration_status,
        ],
    )
    conn.executemany(
        "INSERT INTO securities (ticker, cnpj, share_class, valid_from) VALUES (?, ?, ?, ?) "
        "ON CONFLICT DO NOTHING",
        [[s.ticker, s.cnpj, s.share_class, s.valid_from] for s in securities],
    )


def _store_documents(
    conn: duckdb.DuckDBPyConnection,
    cnpj: str,
    docs: cvm.CompanyDocuments,
    source_file_id: UUID,
) -> tuple[int, int]:
    """Insert filings not seen before, with their facts and share counts."""
    facts_by_filing = defaultdict(list)
    for fact in docs.facts:
        facts_by_filing[fact.key].append(fact)
    shares_by_filing = defaultdict(list)
    for share in docs.shares:
        shares_by_filing[share.key].append(share)

    filings_added = facts_added = 0
    for filing in docs.filings:
        exists = conn.execute(
            "SELECT count(*) FROM filings "
            "WHERE cnpj = ? AND doc_type = ? AND reference_date = ? AND version = ?",
            [cnpj, filing.doc_type, filing.reference_date, filing.version],
        ).fetchone()[0]
        if exists:
            continue
        filing_id = conn.execute(
            "INSERT INTO filings (cnpj, doc_type, reference_date, version, received_at, "
            "source_file_id, cvm_document_id, document_url) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "RETURNING id",
            [
                cnpj,
                filing.doc_type,
                filing.reference_date,
                filing.version,
                filing.received_at,
                source_file_id,
                filing.cvm_document_id,
                filing.document_url,
            ],
        ).fetchone()[0]
        facts = facts_by_filing[filing.key]
        if facts:
            conn.executemany(
                "INSERT INTO financial_facts (filing_id, statement, statement_column, basis, "
                "account_code, account_name, fixed_account, period_type, period_start, "
                "period_end, value, unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        filing_id,
                        f.statement,
                        f.statement_column,
                        f.basis,
                        f.account_code,
                        f.account_name,
                        f.fixed_account,
                        f.period_type,
                        f.period_start,
                        f.period_end,
                        f.value,
                        f.unit,
                    ]
                    for f in facts
                ],
            )
        shares = shares_by_filing[filing.key]
        if shares:
            conn.executemany(
                "INSERT INTO shares_outstanding (cnpj, share_class, reference_date, total, "
                "treasury, filing_id, source_file_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    [
                        cnpj,
                        s.share_class,
                        s.reference_date,
                        s.total,
                        s.treasury,
                        filing_id,
                        source_file_id,
                    ]
                    for s in shares
                ],
            )
        filings_added += 1
        facts_added += len(facts)
    return filings_added, facts_added
