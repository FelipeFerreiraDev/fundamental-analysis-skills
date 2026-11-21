"""Décio Bazin ceiling price (Faça Fortuna com Ações, Antes que Seja Tarde).

    ceiling price = average annual cash distributions per share / target dividend yield

Distributions are summed by record date (data-com) over a moving window that ends on the
snapshot date, expressed per current share (adjusted for splits and bonus shares). Two
variants: JCP gross (as B3 publishes) and JCP net of the withholding tax in force on the
payment date.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from engine import __version__
from engine.config import AnalysisConfig
from engine.contract import AnalysisData, FinancialValue, ValuationResult
from engine.contract.indicators import IndicatorsReport
from engine.indicators.core import (
    PER_SHARE_PLACES,
    adjusted_cash_events,
    cash_per_share,
    shift_years,
)
from engine.valuation.common import PRICE_PLACES, not_applicable

FORMULA = "média anual de proventos por ação ÷ dividend yield desejado"


def method_name(net: bool) -> str:
    return "bazin_net" if net else "bazin_gross"


def value_bazin(
    data: AnalysisData,
    indicators: IndicatorsReport,
    ticker: str,
    config: AnalysisConfig,
    *,
    net: bool,
    now: datetime | None = None,
) -> ValuationResult:
    now = now or datetime.now().replace(microsecond=0)
    ticker = ticker.upper()
    method = method_name(net)
    bazin = config.bazin
    years = bazin.lookback_years
    rationale = (
        "Bazin se aplica a empresas com histórico regular de proventos; exige histórico "
        "carregado ao menos desde o início da janela."
    )
    if years is None:
        return not_applicable(
            method,
            ticker,
            data.reference_date,
            "Janela de anos do Bazin não definida em config/defaults.yaml.",
            rationale,
            now,
        )
    price = indicators.values.get("price")
    if price is None:
        return not_applicable(
            method, ticker, data.reference_date, "Preço indisponível.", rationale, now
        )

    end = data.as_of.date()
    start = shift_years(end, -years) + timedelta(days=1)
    events = adjusted_cash_events(data, ticker, bazin)
    if not events:
        return not_applicable(
            method,
            ticker,
            data.reference_date,
            "A empresa não tem proventos em dinheiro registrados.",
            rationale,
            now,
        )
    first = min(e.action.record_date for e in events)
    if first > start:
        return not_applicable(
            method,
            ticker,
            data.reference_date,
            f"Histórico de proventos começa em {first}, depois do início da janela ({start}).",
            rationale,
            now,
        )

    total, selected = cash_per_share(events, start, end, net=net)
    average = (total / years).quantize(PER_SHARE_PLACES)
    if average <= 0:
        return not_applicable(
            method,
            ticker,
            data.reference_date,
            f"Nenhum provento pago nos últimos {years} anos.",
            rationale,
            now,
        )
    sources = sorted({sid for e in selected for sid in e.action.source_ids})
    average_value = FinancialValue(
        value=average,
        unit="BRL/share",
        period={"type": "INSTANT", "end": end},
        nature="derived",
        source_ids=sources,
        confidence="high",
        note=(
            f"soma de {len(selected)} proventos com data-com entre {start} e {end} "
            f"({total.quantize(PER_SHARE_PLACES)} por ação atual) ÷ {years} anos"
            + ("; JCP líquido do IR retido na fonte" if net else "; JCP bruto")
        ),
    )
    ceiling = (average / bazin.target_dividend_yield).quantize(PRICE_PLACES)

    years_without = _empty_years(selected, start, years)
    ltm_key = f"dividends_per_share_ltm_{'net' if net else 'gross'}"
    limitations = [
        "Pressupõe que os proventos da janela se repetirão; não avalia lucro, crescimento "
        "nem a capacidade de manter o payout.",
        "Proventos extraordinários entram na média e podem inflar o preço-teto.",
    ]
    ltm = indicators.values.get(ltm_key)
    if ltm is not None:
        ratio = (ltm.value / average * 100).quantize(Decimal("0.1"))
        limitations.append(
            f"Os proventos dos últimos 12 meses equivalem a {ratio}% da média anual da janela."
        )
    if years_without:
        limitations.append(
            "Períodos de 12 meses sem nenhum provento na janela: " + ", ".join(years_without) + "."
        )
    if net:
        limitations.append(
            "Considera só o IR retido na fonte sobre JCP; outras tributações do investidor "
            "não são consideradas."
        )

    assumptions = [
        {
            "name": "target_dividend_yield",
            "value": bazin.target_dividend_yield,
            "unit": "ratio",
            "justification": "Rendimento mínimo de 6% ao ano proposto por Bazin; configurável.",
        },
        {
            "name": "lookback_years",
            "value": Decimal(years),
            "unit": "count",
            "justification": "Janela móvel definida pelo investidor em config/defaults.yaml.",
        },
        {
            "name": "include_jcp_correction",
            "value": "sim" if bazin.include_jcp_correction else "não",
            "justification": "Inclui os 'RENDIMENTOS' (correção do JCP entre data-com e "
            "pagamento), por decisão do investidor.",
        },
    ]
    if net:
        assumptions.append(
            {
                "name": "jcp_withholding_rates",
                "value": "; ".join(
                    f"{r.rate} desde {r.since}" for r in bazin.jcp_withholding_rates
                ),
                "unit": "ratio",
                "justification": "Alíquotas de IR retido sobre JCP pela data de pagamento "
                "(config/defaults.yaml): 15% (Lei 9.249/1995) e 17,5% desde 2026 "
                "(LC 224/2025).",
            }
        )
    return ValuationResult(
        method=method,
        ticker=ticker,
        reference_date=data.reference_date,
        applicable=True,
        formula=FORMULA,
        inputs={"average_dividends_per_share": average_value, "price": price},
        assumptions=assumptions,
        result={"ceiling_price": ceiling, "price": price.value},
        limitations=limitations,
        applicability_rationale=f"Histórico de proventos desde {first}, cobrindo a janela.",
        engine_version=__version__,
        computed_at=now,
    )


def _empty_years(selected, start: date, years: int) -> list[str]:
    empty = []
    for offset in range(years):
        bucket_start = shift_years(start, offset)
        bucket_end = shift_years(start, offset + 1) - timedelta(days=1)
        if not any(bucket_start <= e.action.record_date <= bucket_end for e in selected):
            empty.append(f"{bucket_start} a {bucket_end}")
    return empty
