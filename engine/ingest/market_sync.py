"""Market and macro data sync: B3 prices and corporate events, brapi quote, BCB SGS series."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from uuid import UUID

import duckdb

from engine.ingest import b3, macro
from engine.ingest.http import Fetcher, RemoteFile
from engine.ingest.manifest import already_ingested, record_source_file
from engine.ingest.sync import TickerNotFoundError, ingestion_run, transaction


@dataclass
class MarketReport:
    tickers: list[str] = field(default_factory=list)
    price_files_loaded: list[str] = field(default_factory=list)
    price_files_unchanged: list[str] = field(default_factory=list)
    prices_added: int = 0
    last_trade_date: date | None = None
    events_added: int = 0
    quote: macro.Quote | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class MacroReport:
    points_added: int = 0
    last_points: dict[str, tuple[date, str]] = field(default_factory=dict)


def _company_securities(conn: duckdb.DuckDBPyConnection, ticker: str) -> tuple[str, list[tuple]]:
    row = conn.execute("SELECT cnpj FROM securities WHERE ticker = ?", [ticker]).fetchone()
    if row is None:
        raise TickerNotFoundError(f"{ticker} ainda não está no banco — rode o sync da CVM antes")
    securities = conn.execute(
        "SELECT ticker, share_class FROM securities WHERE cnpj = ? AND valid_to IS NULL "
        "ORDER BY ticker",
        [row[0]],
    ).fetchall()
    return row[0], securities


def sync_market(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    *,
    cotahist_base_url: str,
    listed_base_url: str,
    brapi_base_url: str,
    brapi_token: str | None,
    fetcher: Fetcher,
    years: int,
    today: date | None = None,
) -> MarketReport:
    today = today or date.today()
    ticker = ticker.strip().upper()
    cnpj, securities = _company_securities(conn, ticker)
    report = MarketReport(tickers=[t for t, _ in securities])

    _sync_prices(conn, cnpj, set(report.tickers), cotahist_base_url, fetcher, years, today, report)
    _sync_events(conn, cnpj, ticker[:4], securities, listed_base_url, fetcher, report)
    if brapi_token:
        _sync_quote(conn, cnpj, ticker, brapi_base_url, brapi_token, fetcher, report)
    else:
        report.warnings.append("BRAPI_TOKEN vazio: cotação do dia não carregada")
    report.last_trade_date = conn.execute(
        "SELECT max(trade_date) FROM prices_daily WHERE ticker = ?", [ticker]
    ).fetchone()[0]
    return report


def _sync_prices(
    conn: duckdb.DuckDBPyConnection,
    cnpj: str,
    tickers: set[str],
    base: str,
    fetcher: Fetcher,
    years: int,
    today: date,
    report: MarketReport,
) -> None:
    with ingestion_run(conn, "b3", "cotahist") as run_id:
        for year in range(today.year - years + 1, today.year + 1):
            url = f"{base}/COTAHIST_A{year}.ZIP"
            meta = fetcher.metadata(url)
            if meta is None:
                continue
            name = url.rsplit("/", 1)[-1]
            if already_ingested(conn, meta, cnpj):
                report.price_files_unchanged.append(name)
                continue
            remote = fetcher.fetch(url)
            prices = b3.parse_cotahist(remote.path, tickers)
            with transaction(conn):
                source_file_id = record_source_file(
                    conn, run_id, remote, rows_loaded=len(prices), cnpjs=[cnpj]
                )
                before = _count(conn, "prices_daily")
                if prices:
                    conn.executemany(
                        "INSERT INTO prices_daily (ticker, trade_date, open, high, low, close, "
                        "volume, trades, source, source_file_id) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'b3_cotahist', ?) ON CONFLICT DO NOTHING",
                        [
                            [
                                p.ticker,
                                p.trade_date,
                                p.open,
                                p.high,
                                p.low,
                                p.close,
                                p.volume,
                                p.trades,
                                source_file_id,
                            ]
                            for p in prices
                        ],
                    )
                report.prices_added += _count(conn, "prices_daily") - before
                latest_isin = {p.ticker: p.isin for p in prices}  # prices are sorted by date
                for price_ticker, isin in latest_isin.items():
                    conn.execute(
                        "UPDATE securities SET isin = ? "
                        "WHERE ticker = ? AND isin IS DISTINCT FROM ?",
                        [isin, price_ticker, isin],
                    )
            report.price_files_loaded.append(name)


def _sync_events(
    conn: duckdb.DuckDBPyConnection,
    cnpj: str,
    issuer: str,
    securities: list[tuple],
    base: str,
    fetcher: Fetcher,
    report: MarketReport,
) -> None:
    with ingestion_run(conn, "b3", "corporate_events") as run_id:
        supplement_file = fetcher.download(b3.supplement_url(base, issuer))
        supplement = b3.parse_supplement(_json(supplement_file))

        pages: list[tuple[RemoteFile, dict]] = []
        page_number = 1
        while True:
            remote = fetcher.download(
                b3.cash_dividends_url(base, supplement.trading_name, page_number)
            )
            payload = _json(remote)
            pages.append((remote, payload))
            if page_number >= int((payload.get("page") or {}).get("totalPages") or 1):
                break
            page_number += 1

        isins = dict(
            conn.execute("SELECT ticker, isin FROM securities WHERE cnpj = ?", [cnpj]).fetchall()
        )
        with transaction(conn):
            supplement_id = record_source_file(
                conn, run_id, supplement_file, rows_loaded=0, cnpjs=[cnpj]
            )
            for ticker, share_class in securities:
                skipped: set[str] = set()
                for remote, payload in pages:
                    events, ignored = b3.parse_cash_dividends([payload], share_class, supplement)
                    skipped.update(ignored)
                    page_id = record_source_file(
                        conn, run_id, remote, rows_loaded=len(events), cnpjs=[cnpj]
                    )
                    report.events_added += _insert_events(conn, ticker, events, page_id)
                if isins.get(ticker):
                    stock = b3.parse_stock_events(supplement, isins[ticker], share_class)
                    report.events_added += _insert_events(conn, ticker, stock, supplement_id)
                else:
                    report.warnings.append(
                        f"{ticker}: ISIN desconhecido, desdobramentos e grupamentos não carregados"
                    )
                if skipped:
                    report.warnings.append(
                        f"{ticker}: tipos de provento ignorados: {', '.join(sorted(skipped))}"
                    )


def _insert_events(
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    events: list[b3.CorporateEvent],
    source_file_id: UUID,
) -> int:
    added = 0
    for e in events:
        exists = conn.execute(
            """
            SELECT count(*) FROM corporate_actions
            WHERE ticker = ? AND action_type = ? AND record_date = ? AND source_label = ?
              AND value_per_share IS NOT DISTINCT FROM ? AND factor IS NOT DISTINCT FROM ?
            """,
            [ticker, e.action_type, e.record_date, e.source_label, e.value_per_share, e.factor],
        ).fetchone()[0]
        if exists:
            continue
        conn.execute(
            """
            INSERT INTO corporate_actions (ticker, action_type, declared_at, record_date,
                payment_date, value_per_share, is_gross, factor, source_file_id, share_class,
                source_label, related_to)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                ticker,
                e.action_type,
                e.declared_at,
                e.record_date,
                e.payment_date,
                e.value_per_share,
                True if e.action_type == "jcp" else None,
                e.factor,
                source_file_id,
                e.share_class,
                e.source_label,
                e.related_to,
            ],
        )
        added += 1
    return added


def _sync_quote(
    conn: duckdb.DuckDBPyConnection,
    cnpj: str,
    ticker: str,
    base: str,
    token: str,
    fetcher: Fetcher,
    report: MarketReport,
) -> None:
    with ingestion_run(conn, "brapi", "quote") as run_id:
        remote = fetcher.download(
            macro.brapi_quote_url(base, ticker), headers={"Authorization": f"Bearer {token}"}
        )
        quote = macro.parse_brapi_quote(_json(remote), ticker)
        with transaction(conn):
            source_file_id = record_source_file(conn, run_id, remote, rows_loaded=1, cnpjs=[cnpj])
            conn.execute(
                "INSERT INTO market_quotes (ticker, quoted_at, price, source, source_file_id) "
                "VALUES (?, ?, ?, 'brapi', ?) ON CONFLICT DO NOTHING",
                [quote.ticker, quote.quoted_at, quote.price, source_file_id],
            )
        report.quote = quote


def sync_macro(
    conn: duckdb.DuckDBPyConnection,
    *,
    sgs_base_url: str,
    fetcher: Fetcher,
    years: int,
    today: date | None = None,
) -> MacroReport:
    today = today or date.today()
    report = MacroReport()
    start = date(today.year - years + 1, 1, 1)
    with ingestion_run(conn, "bcb", "sgs") as run_id:
        for code, (series_code, _) in macro.SGS_SERIES.items():
            for window_start, window_end in macro.sgs_windows(start, today):
                remote = fetcher.download(
                    macro.sgs_url(sgs_base_url, code, window_start, window_end)
                )
                points = macro.parse_sgs(_json(remote), code, until=today)
                with transaction(conn):
                    source_file_id = record_source_file(
                        conn, run_id, remote, rows_loaded=len(points), cnpjs=[]
                    )
                    before = _count(conn, "macro_series")
                    if points:
                        conn.executemany(
                            "INSERT INTO macro_series (series_code, ref_date, value, unit, "
                            "source_file_id) VALUES (?, ?, ?, 'ratio', ?) ON CONFLICT DO NOTHING",
                            [[p.series_code, p.ref_date, p.value, source_file_id] for p in points],
                        )
                    report.points_added += _count(conn, "macro_series") - before
            last = conn.execute(
                "SELECT ref_date, value FROM macro_series WHERE series_code = ? "
                "ORDER BY ref_date DESC LIMIT 1",
                [series_code],
            ).fetchone()
            if last:
                report.last_points[series_code] = (last[0], f"{last[1]:f}")
    return report


def _json(remote: RemoteFile):
    return json.loads(remote.path.read_bytes())


def _count(conn: duckdb.DuckDBPyConnection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
