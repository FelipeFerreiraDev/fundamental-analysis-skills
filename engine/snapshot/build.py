"""Builds `analyses/<TICKER>/<reference-date>/data.json` from the local warehouse.

The snapshot is the only input of the specialists. Every value carries its source, and the
file records the moment it was taken, so later syncs never change an analysis already made.
Values come out exactly as stored: the only arithmetic done here is shares outstanding
(issued minus treasury) and the 12-month IPCA, both marked as derived.
"""

from __future__ import annotations

import calendar
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import duckdb

from engine.contract import AnalysisData, CorporateAction, FinancialValue, Source
from engine.indicators.rates import compound
from engine.settings import PROJECT_ROOT

ANALYSES_DIR = PROJECT_ROOT / "analyses"
CAPITAL_CLASS = {"ON": "ON", "PN": "PN", "PNA": "PN", "PNB": "PN"}


class SnapshotError(LookupError):
    pass


class _Sources:
    """Collects the sources and ingestion runs referenced by the snapshot."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self.conn = conn
        self.items: dict[str, Source] = {}
        self.runs: set[str] = set()

    def _file(self, source_file_id: UUID) -> tuple:
        row = self.conn.execute(
            "SELECT url, retrieved_at, sha256, ingestion_run_id FROM source_files WHERE id = ?",
            [source_file_id],
        ).fetchone()
        self.runs.add(str(row[3]))
        return row

    def filing(self, filing_id: UUID) -> str:
        doc_type, ref, version, received_at, document_url, source_file_id = self.conn.execute(
            "SELECT doc_type, reference_date, version, received_at, document_url, source_file_id "
            "FROM filings WHERE id = ?",
            [filing_id],
        ).fetchone()
        source_id = f"cvm-{doc_type.lower()}-{ref:%Y-%m-%d}-v{version}"
        if source_id not in self.items:
            url, retrieved_at, sha256, _ = self._file(source_file_id)
            title = f"CVM {doc_type} {ref:%Y-%m-%d} versão {version}"
            if document_url:
                title += f" — documento original: {document_url}"
            self.items[source_id] = Source(
                id=source_id,
                provider="cvm",
                document_type=doc_type,
                title=title,
                url=url,
                published_at=received_at,
                retrieved_at=retrieved_at,
                version=version,
                sha256=sha256,
                extraction="structured",
            )
        return source_id

    def file(self, source_file_id: UUID, provider: str, document_type: str, title: str) -> str:
        url, retrieved_at, sha256, _ = self._file(source_file_id)
        source_id = f"{provider}-{document_type.lower()}-{sha256[:12]}"
        if source_id not in self.items:
            self.items[source_id] = Source(
                id=source_id,
                provider=provider,
                document_type=document_type,
                title=title,
                url=url,
                retrieved_at=retrieved_at,
                sha256=sha256,
                extraction="structured",
            )
        return source_id


def build_snapshot(
    conn: duckdb.DuckDBPyConnection, ticker: str, *, as_of: datetime | None = None
) -> AnalysisData:
    as_of = as_of or datetime.now().replace(microsecond=0)
    ticker = ticker.strip().upper()
    company_row = conn.execute(
        """
        SELECT c.cnpj, c.cvm_code, c.name, c.accounting_template, c.sector
        FROM securities AS s JOIN companies AS c ON c.cnpj = s.cnpj
        WHERE s.ticker = ?
        """,
        [ticker],
    ).fetchone()
    if company_row is None:
        raise SnapshotError(f"{ticker} não está no banco — rode: skillsinvest sync {ticker}")
    cnpj, cvm_code, name, template, sector = company_row
    if sector is None:
        raise SnapshotError(
            f"{ticker} sem perfil setorial — defina-o em config/sector_overrides.yaml e rode o sync"
        )
    securities = conn.execute(
        "SELECT ticker, share_class FROM securities WHERE cnpj = ? AND valid_to IS NULL "
        "ORDER BY ticker",
        [cnpj],
    ).fetchall()
    reference_date = conn.execute(
        "SELECT max(reference_date) FROM filings WHERE cnpj = ?", [cnpj]
    ).fetchone()[0]
    if reference_date is None:
        raise SnapshotError(f"{ticker} não tem demonstrações carregadas")

    sources = _Sources(conn)
    prices = _prices(conn, securities, sources)
    shares = _shares(conn, cnpj, securities, reference_date, sources)
    financials = _financials(conn, cnpj, reference_date, sources)
    macro = _macro(conn, as_of.date(), sources)
    actions = _corporate_actions(conn, securities, sources)
    return AnalysisData(
        company={
            "name": name,
            "cnpj": cnpj,
            "cvm_code": cvm_code,
            "accounting_template": template,
            "sector": sector,
            "securities": [{"ticker": t, "share_class": c} for t, c in securities],
        },
        reference_date=reference_date,
        as_of=as_of,
        ingestion_run_ids=sorted(sources.runs),
        market={"prices": prices, "shares_outstanding": shares},
        financials=financials,
        macro=macro,
        corporate_actions=actions,
        sources=list(sources.items.values()),
    )


def _financials(
    conn: duckdb.DuckDBPyConnection, cnpj: str, reference_date: date, sources: _Sources
) -> dict[str, list[FinancialValue]]:
    rows = conn.execute(
        """
        SELECT concept, period_type, period_start, period_end, value, unit, filing_id
        FROM v_concept_facts
        WHERE cnpj = ? AND basis = 'consolidated' AND period_end <= ?
        ORDER BY concept, period_end, period_type
        """,
        [cnpj, reference_date],
    ).fetchall()
    financials: dict[str, list[FinancialValue]] = defaultdict(list)
    for concept, period_type, start, end, value, unit, filing_id in rows:
        financials[concept].append(
            FinancialValue(
                value=value,
                unit=unit,
                period={"type": period_type, "start": start, "end": end},
                basis="consolidated",
                nature="reported",
                source_ids=[sources.filing(filing_id)],
                confidence="high",
            )
        )
    return dict(financials)


def _shares(
    conn: duckdb.DuckDBPyConnection,
    cnpj: str,
    securities: list[tuple],
    reference_date: date,
    sources: _Sources,
) -> dict[str, FinancialValue]:
    shares = {}
    for ticker, share_class in securities:
        row = conn.execute(
            """
            SELECT so.reference_date, so.total, so.treasury, so.filing_id
            FROM shares_outstanding AS so JOIN filings AS f ON f.id = so.filing_id
            WHERE so.cnpj = ? AND so.share_class = ? AND so.reference_date <= ?
            ORDER BY so.reference_date DESC, f.received_at DESC, f.version DESC
            LIMIT 1
            """,
            [cnpj, CAPITAL_CLASS.get(share_class, share_class), reference_date],
        ).fetchone()
        if row is None:
            continue
        ref, total, treasury, filing_id = row
        shares[ticker] = FinancialValue(
            value=Decimal(total - treasury),
            unit="shares",
            period={"type": "INSTANT", "end": ref},
            nature="derived",
            source_ids=[sources.filing(filing_id)],
            confidence="high",
            note=f"ações emitidas ({total}) − ações em tesouraria ({treasury})",
        )
    return shares


def _prices(
    conn: duckdb.DuckDBPyConnection, securities: list[tuple], sources: _Sources
) -> dict[str, FinancialValue]:
    prices = {}
    for ticker, _ in securities:
        close = conn.execute(
            "SELECT trade_date, close, source_file_id FROM prices_daily "
            "WHERE ticker = ? ORDER BY trade_date DESC LIMIT 1",
            [ticker],
        ).fetchone()
        quote = conn.execute(
            "SELECT quoted_at, price, source_file_id FROM market_quotes "
            "WHERE ticker = ? ORDER BY quoted_at DESC LIMIT 1",
            [ticker],
        ).fetchone()
        if quote is not None and (close is None or quote[0].date() > close[0]):
            quoted_at, price, file_id = quote
            source_id = sources.file(
                file_id, "brapi", "quote", f"Cotação brapi de {ticker} em {quoted_at} UTC"
            )
            day = quoted_at.date()
        elif close is not None:
            day, price, file_id = close
            source_id = sources.file(
                file_id, "b3", "COTAHIST", f"Fechamento de {ticker} no COTAHIST da B3"
            )
        else:
            continue
        prices[ticker] = FinancialValue(
            value=price,
            unit="BRL/share",
            period={"type": "INSTANT", "end": day},
            nature="reported",
            source_ids=[source_id],
            confidence="high",
        )
    return prices


def _macro(
    conn: duckdb.DuckDBPyConnection, today: date, sources: _Sources
) -> dict[str, list[FinancialValue]]:
    macro: dict[str, list[FinancialValue]] = {}
    selic = conn.execute(
        "SELECT ref_date, value, source_file_id FROM macro_series "
        "WHERE series_code = 'bcb_sgs_432' AND ref_date <= ? ORDER BY ref_date DESC LIMIT 1",
        [today],
    ).fetchone()
    if selic:
        macro["selic_target"] = [
            FinancialValue(
                value=selic[1],
                unit="ratio",
                period={"type": "INSTANT", "end": selic[0]},
                nature="reported",
                source_ids=[sources.file(selic[2], "bcb", "SGS", "Meta Selic (SGS 432)")],
                confidence="high",
            )
        ]
    ipca = conn.execute(
        "SELECT ref_date, value, source_file_id FROM macro_series "
        "WHERE series_code = 'bcb_sgs_433' AND ref_date <= ? ORDER BY ref_date DESC LIMIT 12",
        [today],
    ).fetchall()
    if len(ipca) == 12:
        ipca.sort()
        first, last = ipca[0][0], ipca[-1][0]
        end = date(last.year, last.month, calendar.monthrange(last.year, last.month)[1])
        source_ids = sorted(
            {sources.file(row[2], "bcb", "SGS", "IPCA mensal (SGS 433)") for row in ipca}
        )
        macro["ipca_12m"] = [
            FinancialValue(
                value=compound(row[1] for row in ipca),
                unit="ratio",
                period={"type": "LTM", "start": first, "end": end},
                nature="derived",
                source_ids=source_ids,
                confidence="high",
                note=(
                    f"IPCA acumulado de {first:%m/%Y} a {last:%m/%Y}: "
                    "produto de (1 + taxa mensal) − 1"
                ),
            )
        ]
    return macro


def _corporate_actions(
    conn: duckdb.DuckDBPyConnection, securities: list[tuple], sources: _Sources
) -> list[CorporateAction]:
    tickers = [ticker for ticker, _ in securities]
    rows = conn.execute(
        """
        SELECT ticker, action_type, source_label, declared_at, record_date, payment_date,
               value_per_share, is_gross, factor, related_to, source_file_id
        FROM corporate_actions WHERE list_contains(?, ticker)
        ORDER BY record_date, ticker, action_type
        """,
        [tickers],
    ).fetchall()
    actions = []
    for row in rows:
        (
            ticker,
            action_type,
            label,
            declared,
            record,
            payment,
            value,
            gross,
            factor,
            related,
            file_id,
        ) = row
        actions.append(
            CorporateAction(
                ticker=ticker,
                action_type=action_type,
                source_label=label or action_type,
                declared_at=declared,
                record_date=record,
                payment_date=payment,
                value_per_share=value,
                is_gross=gross,
                factor=factor,
                related_to=related,
                source_ids=[
                    sources.file(file_id, "b3", "corporate_events", "Proventos e eventos — B3")
                ],
            )
        )
    return actions


def analysis_dir(ticker: str, reference_date: date, root: Path = ANALYSES_DIR) -> Path:
    return root / ticker.upper() / f"{reference_date:%Y-%m-%d}"


def write_snapshot(data: AnalysisData, ticker: str, root: Path = ANALYSES_DIR) -> Path:
    path = analysis_dir(ticker, data.reference_date, root) / "data.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(data.model_dump_json())
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
