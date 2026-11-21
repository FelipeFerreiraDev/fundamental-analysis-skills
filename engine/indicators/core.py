"""Indicators computed from a snapshot (`indicators.json`).

Every indicator is a derived `FinancialValue` whose note states the formula and whose
source_ids are the union of its inputs' sources, so it can be audited back to documents.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

from engine import __version__
from engine.config import BazinConfig
from engine.contract import AnalysisData, CorporateAction, FinancialValue
from engine.contract.indicators import IndicatorsReport

PER_SHARE_PLACES = Decimal("0.00000001")
SHARE_EVENTS = ("split", "reverse_split", "bonus_shares")
CASH_EVENTS = ("dividend", "jcp", "other")


class IndicatorError(ValueError):
    """An indicator cannot be computed from the available data."""


def shift_years(day: date, years: int) -> date:
    """Same day `years` earlier (or later); 29 February falls back to the 28th."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def _sources(*values: FinancialValue) -> list[str]:
    return sorted({sid for v in values for sid in v.source_ids})


def _derived(value, unit, period, note, *inputs, confidence="high") -> FinancialValue:
    return FinancialValue(
        value=value,
        unit=unit,
        period=period,
        nature="derived",
        source_ids=_sources(*inputs),
        confidence=confidence,
        note=note,
    )


def _brl(value: Decimal) -> str:
    return f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _find(series: list[FinancialValue], period_type: str, end: date, start: date | None = None):
    for value in series:
        same_period = value.period.type == period_type and value.period.end == end
        if same_period and (start is None or value.period.start == start):
            return value
    return None


# Accounting --------------------------------------------------------------------------


def ltm_flow(data: AnalysisData, concept: str) -> FinancialValue:
    """Last twelve months ending at the reference date.

    At a fiscal year end it is the FY value. Otherwise: YTD(current) + FY(previous year)
    - YTD(same period of the previous year), all taken from the latest filings.
    """
    series = data.financials.get(concept, [])
    ref = data.reference_date
    start = shift_years(ref, -1) + timedelta(days=1)
    period = {"type": "LTM", "start": start, "end": ref}
    fiscal_year = _find(series, "FY", ref)
    if fiscal_year is not None:
        return _derived(
            fiscal_year.value,
            fiscal_year.unit,
            period,
            f"{concept} do exercício {ref.year}",
            fiscal_year,
        )
    year_start = date(ref.year, 1, 1)
    current = _find(series, "YTD", ref, year_start)
    previous_fy = _find(series, "FY", date(ref.year - 1, 12, 31))
    previous_ytd = _find(series, "YTD", shift_years(ref, -1), date(ref.year - 1, 1, 1))
    missing = [
        name
        for name, value in (
            (f"acumulado até {ref}", current),
            (f"exercício {ref.year - 1}", previous_fy),
            (f"acumulado até {shift_years(ref, -1)}", previous_ytd),
        )
        if value is None
    ]
    if missing:
        raise IndicatorError(f"{concept}: faltam {', '.join(missing)} para os últimos 12 meses")
    return _derived(
        current.value + previous_fy.value - previous_ytd.value,
        current.unit,
        period,
        f"{concept}: acumulado até {ref} ({_brl(current.value)}) + exercício {ref.year - 1} "
        f"({_brl(previous_fy.value)}) − acumulado até {shift_years(ref, -1)} "
        f"({_brl(previous_ytd.value)})",
        current,
        previous_fy,
        previous_ytd,
    )


def equity_at(data: AnalysisData, day: date) -> FinancialValue:
    """Equity attributable to the controlling shareholders at `day`.

    Old bank layouts do not report it: then it is total equity minus non-controlling
    interests (docs/architecture.md §7.2).
    """
    reported = _find(data.financials.get("equity", []), "INSTANT", day)
    if reported is not None:
        return reported
    total = _find(data.financials.get("equity_total", []), "INSTANT", day)
    minorities = _find(data.financials.get("non_controlling_interests", []), "INSTANT", day)
    if total is None or minorities is None:
        raise IndicatorError(f"patrimônio do controlador indisponível em {day}")
    return _derived(
        total.value - minorities.value,
        "BRL",
        {"type": "INSTANT", "end": day},
        f"patrimônio total ({_brl(total.value)}) − não controladores ({_brl(minorities.value)})",
        total,
        minorities,
    )


# Corporate actions --------------------------------------------------------------------


@dataclass(frozen=True)
class AdjustedCash:
    action: CorporateAction
    adjustment_factor: Decimal  # cumulative new-shares-per-old after the record date
    gross: Decimal  # per current share
    net: Decimal  # per current share, JCP net of withholding tax
    withholding_rate: Decimal


def adjusted_cash_events(data: AnalysisData, ticker: str, bazin: BazinConfig) -> list[AdjustedCash]:
    """Cash events expressed per current share.

    A share event (split, reverse split, bonus) whose record date is on or after a cash
    event's record date changed the number of shares that event was paid on, so the cash
    value is divided by the cumulative factor of all such later share events.
    """
    actions = [a for a in data.corporate_actions if a.ticker == ticker]
    share_events = [a for a in actions if a.action_type in SHARE_EVENTS]
    result = []
    for action in actions:
        if action.action_type not in CASH_EVENTS:
            continue
        if action.action_type == "other" and not bazin.include_jcp_correction:
            continue
        factor = Decimal(1)
        for event in share_events:
            if event.record_date >= action.record_date:
                factor *= event.factor
        gross = action.value_per_share / factor
        rate = Decimal(0)
        if action.action_type == "jcp":
            rate = bazin.jcp_rate_on(action.payment_date or action.record_date)
        result.append(
            AdjustedCash(
                action=action,
                adjustment_factor=factor,
                gross=gross,
                net=gross * (1 - rate),
                withholding_rate=rate,
            )
        )
    return result


def cash_per_share(
    events: list[AdjustedCash], start: date, end: date, *, net: bool
) -> tuple[Decimal, list[AdjustedCash]]:
    """Sum per current share of events with record date in [start, end]."""
    selected = [e for e in events if start <= e.action.record_date <= end]
    total = sum((e.net if net else e.gross for e in selected), Decimal(0))
    return total, selected


def _cash_value(
    events: list[AdjustedCash],
    start: date,
    end: date,
    net: bool,
    period: dict,
    label: str,
    dataset_sources: list[str],
) -> FinancialValue:
    """Cash per share in a window. With no event, the source is the events dataset itself."""
    total, selected = cash_per_share(events, start, end, net=net)
    kinds = sorted({e.action.source_label for e in selected})
    note = (
        f"{label}: soma de {len(selected)} proventos com data-com entre {start} e {end} "
        f"({', '.join(kinds) or 'nenhum'}), por ação atual (ajustados por desdobramentos, "
        f"grupamentos e bonificações)"
    )
    if net:
        note += "; JCP líquido do IR retido na fonte pela alíquota da data de pagamento"
    return FinancialValue(
        value=total.quantize(PER_SHARE_PLACES),
        unit="BRL/share",
        period=period,
        nature="derived",
        source_ids=sorted({sid for e in selected for sid in e.action.source_ids})
        or dataset_sources,
        confidence="high",
        note=note,
    )


# Report --------------------------------------------------------------------------------


def compute_indicators(
    data: AnalysisData, ticker: str, bazin: BazinConfig, *, now: datetime | None = None
) -> IndicatorsReport:
    ticker = ticker.upper()
    values: dict[str, FinancialValue] = {}
    series: dict[str, list[FinancialValue]] = {}
    unavailable: dict[str, str] = {}
    price = data.market.prices.get(ticker)
    shares = data.market.shares_outstanding.get(ticker)
    ref = data.reference_date

    def attempt(name, builder):
        try:
            values[name] = builder()
        except IndicatorError as exc:
            unavailable[name] = str(exc)

    attempt("net_income_ltm", lambda: ltm_flow(data, "net_income"))
    attempt("equity", lambda: equity_at(data, ref))
    if shares is None:
        unavailable["shares_outstanding"] = "quantidade de ações ausente no snapshot"
    else:
        values["shares_outstanding"] = shares
    if price is not None:
        values["price"] = price

    if "net_income_ltm" in values and shares is not None:
        ni = values["net_income_ltm"]
        values["eps_ltm"] = _derived(
            (ni.value / shares.value).quantize(PER_SHARE_PLACES),
            "BRL/share",
            ni.period.model_dump(),
            "lucro líquido do controlador nos últimos 12 meses ÷ ações em circulação na "
            "data-base (o LPA reportado usa a média ponderada de ações)",
            ni,
            shares,
        )
    if "equity" in values and shares is not None:
        eq = values["equity"]
        values["bvps"] = _derived(
            (eq.value / shares.value).quantize(PER_SHARE_PLACES),
            "BRL/share",
            {"type": "INSTANT", "end": ref},
            "patrimônio do controlador ÷ ações em circulação na data-base",
            eq,
            shares,
        )
    if "net_income_ltm" in values and "equity" in values:
        try:
            opening = equity_at(data, shift_years(ref, -1))
            ni, closing = values["net_income_ltm"], values["equity"]
            average = (opening.value + closing.value) / 2
            values["roe_ltm"] = _derived(
                ni.value / average,
                "ratio",
                ni.period.model_dump(),
                "lucro dos últimos 12 meses ÷ média do patrimônio do controlador no início e "
                "no fim do período",
                ni,
                opening,
                closing,
            )
        except IndicatorError as exc:
            unavailable["roe_ltm"] = str(exc)

    if price is not None:
        for name, base, label in (
            ("pe_ratio", "eps_ltm", "preço ÷ LPA dos últimos 12 meses"),
            ("pb_ratio", "bvps", "preço ÷ valor patrimonial por ação"),
        ):
            if base not in values:
                unavailable[name] = f"{base} indisponível"
            elif values[base].value <= 0:
                unavailable[name] = f"{base} não positivo: múltiplo sem significado"
            else:
                values[name] = _derived(
                    price.value / values[base].value,
                    "ratio",
                    {"type": "INSTANT", "end": price.period.end},
                    label,
                    price,
                    values[base],
                )

    events = adjusted_cash_events(data, ticker, bazin)
    dataset_sources = sorted(
        {sid for a in data.corporate_actions if a.ticker == ticker for sid in a.source_ids}
    )
    if not dataset_sources:
        unavailable["dividends"] = "histórico de proventos ausente no snapshot"
    as_of_day = data.as_of.date()
    ltm_start = shift_years(as_of_day, -1) + timedelta(days=1)
    ltm_period = {"type": "LTM", "start": ltm_start, "end": as_of_day}
    for suffix, net in (("gross", False), ("net", True)) if dataset_sources else ():
        dps = _cash_value(
            events, ltm_start, as_of_day, net, ltm_period, "últimos 12 meses", dataset_sources
        )
        values[f"dividends_per_share_ltm_{suffix}"] = dps
        if price is not None:
            values[f"dividend_yield_ltm_{suffix}"] = _derived(
                dps.value / price.value,
                "ratio",
                {"type": "INSTANT", "end": price.period.end},
                "proventos por ação dos últimos 12 meses ÷ preço",
                dps,
                price,
            )
        years = sorted({e.action.record_date.year for e in events})
        series[f"dividends_per_share_annual_{suffix}"] = [
            _cash_value(
                events,
                date(year, 1, 1),
                date(year, 12, 31),
                net,
                {"type": "FY", "start": date(year, 1, 1), "end": date(year, 12, 31)},
                f"ano {year}",
                dataset_sources,
            )
            for year in years
            if date(year, 12, 31) <= as_of_day
        ]

    annual = [v for v in data.financials.get("net_income", []) if v.period.type == "FY"]
    if annual:
        series["net_income_annual"] = annual

    return IndicatorsReport(
        ticker=ticker,
        reference_date=ref,
        snapshot_as_of=data.as_of,
        generated_at=now or datetime.now().replace(microsecond=0),
        engine_version=__version__,
        values=values,
        series=series,
        unavailable=unavailable,
    )
