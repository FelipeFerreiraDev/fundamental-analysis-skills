"""Data checks behind `validation.json` (docs/architecture.md §5, data-validator).

Checks on the snapshot alone are pure functions of `AnalysisData`. Checks that need history
the snapshot does not carry (restatements, daily prices, reported EPS) read the warehouse.
Severity: an `error` blocks every valuation; a `warning` must be shown in the report; an
`info` documents something the reader should know.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

import duckdb

from engine import __version__
from engine.contract import AnalysisData, FinancialValue
from engine.contract.validation import Check, ValidationReport

PRICE_STALE_DAYS = 7
LARGE_MOVE = Decimal("0.15")
EVENT_WINDOW_DAYS = 5
EPS_TOLERANCE = Decimal("0.02")
MIN_ANNUAL_YEARS = 3
CMN_4966_START = date(2025, 1, 1)
CVM_BANK_LAYOUT_CHANGE = date(2020, 1, 1)


def _by_end(series: list[FinancialValue], period_type: str) -> dict[date, FinancialValue]:
    return {v.period.end: v for v in series if v.period.type == period_type}


def _brl(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


# Snapshot-only checks -----------------------------------------------------------------


def check_balance_sheet_identity(data: AnalysisData) -> Check:
    assets = _by_end(data.financials.get("total_assets", []), "INSTANT")
    liabilities = _by_end(data.financials.get("total_liabilities_and_equity", []), "INSTANT")
    common = sorted(set(assets) & set(liabilities))
    mismatches = [
        f"{day}: ativo {_brl(assets[day].value)} ≠ passivo + PL {_brl(liabilities[day].value)}"
        for day in common
        if assets[day].value != liabilities[day].value
    ]
    return Check(
        id="balance_sheet_identity",
        severity="error",
        passed=bool(common) and not mismatches,
        message=(
            f"Ativo total igual a passivo + patrimônio em {len(common)} balanços."
            if common and not mismatches
            else "Ativo total diferente de passivo + patrimônio, ou balanços ausentes."
        ),
        details=mismatches or ([] if common else ["nenhum balanço com ativo e passivo totais"]),
    )


def check_required_inputs(data: AnalysisData, ticker: str) -> Check:
    """Inputs every phase-1 method depends on, at the snapshot reference date."""
    missing = []
    if ticker not in data.market.prices:
        missing.append(f"cotação de {ticker}")
    if ticker not in data.market.shares_outstanding:
        missing.append(f"quantidade de ações de {ticker}")
    annual = _by_end(data.financials.get("net_income", []), "FY")
    if len(annual) < MIN_ANNUAL_YEARS:
        missing.append(f"lucro líquido anual de ao menos {MIN_ANNUAL_YEARS} anos ({len(annual)})")
    equity = _by_end(data.financials.get("equity", []), "INSTANT")
    if data.reference_date not in equity:
        missing.append(f"patrimônio do controlador na data-base {data.reference_date}")
    if not data.corporate_actions:
        missing.append("histórico de proventos")
    return Check(
        id="required_inputs",
        severity="error",
        passed=not missing,
        message="Todos os dados mínimos estão presentes."
        if not missing
        else "Faltam dados mínimos para as análises.",
        details=missing,
    )


def check_quarter_consistency(data: AnalysisData) -> Check:
    """A reported quarter must equal the difference of consecutive year-to-date values."""
    problems, compared = [], 0
    for concept, series in sorted(data.financials.items()):
        ytd = _by_end(series, "YTD")
        for end, quarter in _by_end(series, "3M").items():
            current = ytd.get(end)
            if current is None:
                continue
            earlier = [
                v for e, v in ytd.items() if e < end and v.period.start == current.period.start
            ]
            if not earlier:
                continue
            previous = max(earlier, key=lambda v: v.period.end)
            if previous.period.end + timedelta(days=1) != quarter.period.start:
                continue
            compared += 1
            if quarter.value != current.value - previous.value:
                problems.append(
                    f"{concept} {quarter.period.start} a {end}: trimestre "
                    f"{_brl(quarter.value)} ≠ acumulado {_brl(current.value)} − "
                    f"{_brl(previous.value)}"
                )
    return Check(
        id="quarter_consistency",
        severity="warning",
        passed=not problems,
        message=f"{compared} trimestres conferidos contra os acumulados do ano."
        if not problems
        else "Trimestres não batem com a diferença dos acumulados: o documento mais recente "
        "revisou um trimestre anterior dentro do acumulado. Use o acumulado mais recente.",
        details=problems,
    )


def check_zero_flows(data: AnalysisData) -> Check:
    """Annual flows exactly zero usually mean an account the company did not fill."""
    details = [
        f"{concept} {value.period.start} a {value.period.end}: zero ({', '.join(value.source_ids)})"
        for concept, series in sorted(data.financials.items())
        for value in series
        if value.period.type == "FY" and value.value == 0
    ]
    return Check(
        id="zero_flows",
        severity="warning",
        passed=not details,
        message="Nenhum valor anual zerado."
        if not details
        else "Valores anuais exatamente zero: provavelmente contas não preenchidas pela "
        "empresa; não use esses anos na série.",
        details=details,
    )


def check_price_freshness(data: AnalysisData) -> Check:
    details, stale = [], False
    for ticker, price in data.market.prices.items():
        age = (data.as_of.date() - price.period.end).days
        details.append(f"{ticker}: R$ {_brl(price.value)} em {price.period.end} ({age} dias)")
        stale |= age > PRICE_STALE_DAYS
    return Check(
        id="price_freshness",
        severity="warning",
        passed=not stale,
        message="Cotação recente."
        if not stale
        else f"Cotação com mais de {PRICE_STALE_DAYS} dias: rode o sync antes de analisar.",
        details=details,
    )


def check_reference_gap(data: AnalysisData) -> Check:
    gaps = [
        f"{t}: preço em {p.period.end}, balanço em {data.reference_date} "
        f"({(p.period.end - data.reference_date).days} dias depois)"
        for t, p in data.market.prices.items()
    ]
    return Check(
        id="price_after_statements",
        severity="info",
        passed=True,
        message="O preço é posterior ao último balanço: eventos entre as duas datas "
        "não estão nos números contábeis.",
        details=gaps,
    )


def check_accounting_breaks(data: AnalysisData) -> Check:
    details = []
    if data.company.accounting_template == "bank":
        details.append(
            "Layout da CVM para bancos mudou em 2020: algumas contas só são comparáveis "
            "a partir dele (docs/architecture.md §7.2)."
        )
        if data.reference_date >= CMN_4966_START:
            details.append(
                "Resolução CMN 4.966 (vigente desde 01/01/2025): provisão por perda esperada; "
                "provisões, resultado e patrimônio antes e depois de 2025 não são diretamente "
                "comparáveis."
            )
    return Check(
        id="accounting_breaks",
        severity="warning" if len(details) > 1 else "info",
        passed=not details,
        message="Há quebras de série contábil conhecidas no período analisado."
        if details
        else "Nenhuma quebra de série conhecida.",
        details=details,
    )


# Warehouse checks ---------------------------------------------------------------------


def check_restatements(data: AnalysisData, conn: duckdb.DuckDBPyConnection) -> Check:
    """Mapped accounts whose value for a period changed in a later filing."""
    rows = conn.execute(
        """
        SELECT m.concept, ff.period_type, ff.period_end, f.doc_type, f.reference_date,
               f.version, ff.value, ff.account_code
        FROM financial_facts ff
        JOIN filings f ON f.id = ff.filing_id
        JOIN account_map m
          ON m.accounting_template = ? AND m.statement = ff.statement
         AND m.account_code = ff.account_code
         AND f.reference_date >= m.valid_from
         AND (m.valid_to IS NULL OR f.reference_date <= m.valid_to)
        WHERE f.cnpj = ? AND ff.basis = 'consolidated' AND ff.statement_column = ''
        ORDER BY m.concept, ff.period_type, ff.period_end, f.received_at, f.version
        """,
        [data.company.accounting_template, data.company.cnpj],
    ).fetchall()
    history = defaultdict(list)
    for concept, ptype, end, doc, ref, version, value, _code in rows:
        # Keyed by concept (not account code): the same concept may move to another code
        # when the layout changes, and that is still the same economic value.
        history[(concept, ptype, end)].append((doc, ref, version, value))
    details = []
    for (concept, ptype, end), versions in sorted(history.items()):
        distinct = {v[3] for v in versions}
        if len(distinct) > 1:
            first, last = versions[0], versions[-1]
            details.append(
                f"{concept} {ptype} {end}: {_brl(first[3])} ({first[0]} {first[1]} v{first[2]}) "
                f"→ {_brl(last[3])} ({last[0]} {last[1]} v{last[2]})"
            )
    return Check(
        id="restatements",
        severity="warning",
        passed=not details,
        message="Nenhuma reapresentação encontrada."
        if not details
        else f"{len(details)} valores foram reapresentados em documentos posteriores; "
        "a análise usa sempre o valor mais recente.",
        details=details,
    )


def check_large_price_moves(data: AnalysisData, conn: duckdb.DuckDBPyConnection) -> Check:
    details = []
    for ticker in data.market.prices:
        rows = conn.execute(
            """
            SELECT trade_date, close, lag(close) OVER (ORDER BY trade_date) AS previous
            FROM prices_daily WHERE ticker = ? AND trade_date > ?
            ORDER BY trade_date
            """,
            [ticker, data.as_of.date() - timedelta(days=365)],
        ).fetchall()
        events = [a.record_date for a in data.corporate_actions if a.ticker == ticker]
        for day, close, previous in rows:
            if previous is None or previous == 0:
                continue
            change = close / previous - 1
            near_event = any(abs((day - e).days) <= EVENT_WINDOW_DAYS for e in events)
            if abs(change) > LARGE_MOVE and not near_event:
                details.append(
                    f"{ticker} {day}: R$ {_brl(previous)} → R$ {_brl(close)} "
                    f"({change * 100:+.1f}%), sem provento ou evento de ações próximo"
                )
    return Check(
        id="large_price_moves",
        severity="warning",
        passed=not details,
        message="Nenhuma variação diária acima de 15% sem evento nos últimos 12 meses."
        if not details
        else "Variações diárias fortes sem evento de ações: confira notícias e fatos "
        "relevantes antes de usar o preço.",
        details=details,
    )


def check_reported_eps(data: AnalysisData, conn: duckdb.DuckDBPyConnection) -> Check:
    """Net income / shares outstanding should be close to the EPS the company reported."""
    row = conn.execute(
        """
        SELECT ff.value, ff.period_end, f.reference_date
        FROM financial_facts ff JOIN filings f ON f.id = ff.filing_id
        WHERE f.cnpj = ? AND f.doc_type = 'DFP' AND ff.statement = 'DRE'
          AND ff.basis = 'consolidated' AND ff.account_code LIKE '3.99.01.%'
          AND ff.period_type = 'FY'
        ORDER BY ff.period_end DESC, f.received_at DESC LIMIT 1
        """,
        [data.company.cnpj],
    ).fetchone()
    annual = _by_end(data.financials.get("net_income", []), "FY")
    shares = conn.execute(
        """
        SELECT so.total - so.treasury FROM shares_outstanding so
        JOIN filings f ON f.id = so.filing_id
        WHERE so.cnpj = ? AND so.reference_date = ? ORDER BY f.received_at DESC LIMIT 1
        """,
        [data.company.cnpj, row[1] if row else None],
    ).fetchone()
    if row is None or row[1] not in annual or not shares or not shares[0]:
        return Check(
            id="reported_eps",
            severity="info",
            passed=True,
            message="Sem lucro por ação reportado para comparar.",
        )
    reported, end = row[0], row[1]
    implied = annual[end].value / Decimal(shares[0])
    gap = abs(implied / reported - 1) if reported else Decimal(1)
    detail = (
        f"{end}: reportado R$ {reported:.4f} | lucro ÷ ações no fim do ano R$ {implied:.4f} "
        f"(diferença {gap * 100:.2f}%; o reportado usa a média ponderada de ações)"
    )
    return Check(
        id="reported_eps",
        severity="warning",
        passed=gap <= EPS_TOLERANCE,
        message="Lucro e quantidade de ações coerentes com o lucro por ação reportado."
        if gap <= EPS_TOLERANCE
        else "Lucro por ação implícito diverge do reportado: confira lucro e ações.",
        details=[detail],
    )


def run_validation(
    data: AnalysisData,
    conn: duckdb.DuckDBPyConnection,
    ticker: str,
    *,
    now: datetime | None = None,
) -> ValidationReport:
    ticker = ticker.upper()
    if ticker not in {s.ticker for s in data.company.securities}:
        raise ValueError(f"{ticker} não pertence à empresa do snapshot")
    checks = [
        check_required_inputs(data, ticker),
        check_balance_sheet_identity(data),
        check_quarter_consistency(data),
        check_zero_flows(data),
        check_price_freshness(data),
        check_reference_gap(data),
        check_accounting_breaks(data),
        check_restatements(data, conn),
        check_large_price_moves(data, conn),
        check_reported_eps(data, conn),
    ]
    return ValidationReport(
        ticker=ticker,
        reference_date=data.reference_date,
        snapshot_as_of=data.as_of,
        generated_at=now or datetime.now().replace(microsecond=0),
        engine_version=__version__,
        checks=checks,
        blocking=any(c.severity == "error" and not c.passed for c in checks),
    )
