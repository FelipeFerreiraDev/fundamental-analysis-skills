"""Renders analyses/<TICKER>/<data-base>/report.html from the analysis JSON files.

The report never computes financial numbers: every figure comes from data.json,
validation.json, indicators.json or valuations/*.json. The only operations here are
formatting, ordering, and comparing a price with a ceiling the engine already computed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape

from engine import __version__
from engine.contract import SCHEMA_VERSION, ValuationResult
from engine.report import formatting as fmt
from engine.report.charts import column_chart
from engine.snapshot.folder import AnalysisFolder, AnalysisStateError

INDICATORS = [
    ("price", "Preço", ""),
    ("net_income_ltm", "Lucro líquido do controlador (12 meses)", ""),
    ("equity", "Patrimônio do controlador", ""),
    ("shares_outstanding", "Ações em circulação", ""),
    ("eps_ltm", "LPA (12 meses)", ""),
    ("bvps", "VPA", ""),
    ("roe_ltm", "ROE (12 meses)", ""),
    ("pe_ratio", "P/L", "multiple"),
    ("pb_ratio", "P/VP", "multiple"),
    ("dividends_per_share_ltm_gross", "Proventos por ação, 12 meses (JCP bruto)", ""),
    ("dividends_per_share_ltm_net", "Proventos por ação, 12 meses (JCP líquido)", ""),
    ("dividend_yield_ltm_gross", "Dividend yield, 12 meses (JCP bruto)", ""),
    ("dividend_yield_ltm_net", "Dividend yield, 12 meses (JCP líquido)", ""),
]
METHOD_LABELS = {
    "graham_number": "Número de Graham",
    "bazin_gross": "Bazin (JCP bruto)",
    "bazin_net": "Bazin (JCP líquido)",
}
SEVERITY = {
    "error": ("Erro", "critical", 0),
    "warning": ("Aviso", "warning", 1),
    "info": ("Informação", "info", 2),
}


@dataclass(frozen=True)
class MethodRow:
    result: ValuationResult
    label: str
    below_ceiling: list[tuple[str, bool]]


def _environment() -> Environment:
    env = Environment(
        loader=PackageLoader("engine.report", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        brl=fmt.brl,
        brl_compact=fmt.brl_compact,
        percent=fmt.percent,
        multiple=fmt.multiple,
        number=fmt.number,
        day=fmt.day,
        by_unit=fmt.by_unit,
    )
    return env


def _valuations(folder: AnalysisFolder) -> list[ValuationResult]:
    results = []
    for file in sorted((folder.path / "valuations").glob("*.json")):
        result = ValuationResult.model_validate_json(file.read_text(encoding="utf-8"))
        if result.reference_date != folder.data.reference_date:
            raise AnalysisStateError(
                f"{file.name} é de outra data-base — rode: skillsinvest valuate"
            )
        results.append(result)
    if not results:
        raise AnalysisStateError("nenhum valuation calculado — rode: skillsinvest valuate")
    order = list(METHOD_LABELS)
    return sorted(results, key=lambda r: order.index(r.method) if r.method in order else 99)


def _method_row(result: ValuationResult) -> MethodRow:
    checks: list[tuple[str, bool]] = []
    out = result.result
    if result.applicable and out is not None and out.price is not None:
        if out.ceiling_price is not None:
            checks.append(("preço-teto", out.price <= out.ceiling_price))
        for ceiling in out.ceiling_prices:
            checks.append(
                (f"margem {fmt.percent(ceiling.margin_of_safety, 0)}", out.price <= ceiling.price)
            )
    return MethodRow(result, METHOD_LABELS.get(result.method, result.method), checks)


def build_context(folder: AnalysisFolder, ticker: str, *, now: datetime | None = None) -> dict:
    data = folder.data
    validation = folder.validation()
    indicators = folder.indicators()
    ticker = ticker.upper()

    indicator_rows = [
        (label, indicators.values[key], kind)
        for key, label, kind in INDICATORS
        if key in indicators.values
    ]
    net_income = [
        (str(v.period.end.year), v.value) for v in indicators.series.get("net_income_annual", [])
    ]
    dividends = {
        suffix: [
            (str(v.period.end.year), v.value)
            for v in indicators.series.get(f"dividends_per_share_annual_{suffix}", [])
        ]
        for suffix in ("gross", "net")
    }
    net_by_year = dict(dividends["net"])
    charts = {
        "net_income": column_chart(
            "Lucro líquido do controlador por ano",
            net_income,
            axis_format=lambda v: f"{fmt.number(v, 0)} bi",
            value_format=fmt.brl_compact,
            scale=Decimal(10) ** 9,
        ),
        "dividends": column_chart(
            "Proventos por ação por ano (JCP bruto)",
            dividends["gross"][-10:],
            axis_format=lambda v: fmt.brl(v),
            value_format=fmt.brl,
        ),
    }
    issues = sorted(
        (c for c in validation.checks if not c.passed or c.severity == "info"),
        key=lambda c: SEVERITY[c.severity][2],
    )
    results = _valuations(folder)
    sources = {s.id: s for s in data.sources}
    return {
        "ticker": ticker,
        "data": data,
        "company": data.company,
        "price": data.market.prices.get(ticker),
        "validation": validation,
        "issues": issues,
        "passed_checks": [c for c in validation.checks if c.passed and c.severity != "info"],
        "severity": SEVERITY,
        "indicators": indicators,
        "indicator_rows": indicator_rows,
        "net_income": net_income,
        "dividends_gross": dividends["gross"],
        "net_by_year": net_by_year,
        "charts": charts,
        "methods": [_method_row(r) for r in results],
        "sources": sources,
        "engine_version": __version__,
        "schema_version": SCHEMA_VERSION,
        "generated_at": now or datetime.now().replace(microsecond=0),
    }


def render_report(folder: AnalysisFolder, ticker: str, *, now: datetime | None = None) -> Path:
    html = (
        _environment()
        .get_template("report.html.j2")
        .render(**build_context(folder, ticker, now=now))
    )
    path = folder.path / "report.html"
    path.write_text(html, encoding="utf-8")
    return path
