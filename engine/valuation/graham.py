"""Graham Number (Benjamin Graham, The Intelligent Investor).

    fair value = √(22.5 × EPS × BVPS)

22.5 is the product of the two limits Graham set for a defensive purchase: P/E of at most
15 and P/B of at most 1.5. The revised formula of 1974 (EPS × (8.5 + 2g) × 4.4 / Y) needs a
growth estimate and is not implemented yet.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from engine import __version__
from engine.config import AnalysisConfig
from engine.contract import AnalysisData, ValuationResult
from engine.contract.indicators import IndicatorsReport
from engine.valuation.common import PRICE_PLACES, ceiling_prices, margin_at_price, not_applicable

METHOD = "graham_number"
FORMULA = "√(22,5 × LPA × VPA)"
GRAHAM_CONSTANT = Decimal("22.5")


def graham_number(eps: Decimal, bvps: Decimal) -> Decimal:
    if eps <= 0 or bvps <= 0:
        raise ValueError("the Graham Number needs positive EPS and BVPS")
    return (GRAHAM_CONSTANT * eps * bvps).sqrt()


def value_graham(
    data: AnalysisData,
    indicators: IndicatorsReport,
    ticker: str,
    config: AnalysisConfig,
    *,
    now: datetime | None = None,
) -> ValuationResult:
    now = now or datetime.now().replace(microsecond=0)
    ticker = ticker.upper()
    eps = indicators.values.get("eps_ltm")
    bvps = indicators.values.get("bvps")
    price = indicators.values.get("price")
    rationale = (
        "O Número de Graham exige lucro e patrimônio positivos; usa o LPA dos últimos 12 meses "
        "e o VPA da data-base."
    )
    if eps is None or bvps is None or price is None:
        missing = [n for n, v in (("LPA", eps), ("VPA", bvps), ("preço", price)) if v is None]
        return not_applicable(
            METHOD,
            ticker,
            data.reference_date,
            f"Indisponível: {', '.join(missing)}.",
            rationale,
            now,
        )
    if eps.value <= 0:
        return not_applicable(
            METHOD,
            ticker,
            data.reference_date,
            "LPA dos últimos 12 meses não é positivo: a fórmula não se aplica.",
            rationale,
            now,
        )
    if bvps.value <= 0:
        return not_applicable(
            METHOD,
            ticker,
            data.reference_date,
            "Patrimônio por ação não é positivo: a fórmula não se aplica.",
            rationale,
            now,
        )

    fair_value = graham_number(eps.value, bvps.value).quantize(PRICE_PLACES)
    limitations = [
        "Não considera crescimento, qualidade do lucro nem vantagens competitivas.",
        "Usa o lucro dos últimos 12 meses: um período atípico (provisões, ganhos não "
        "recorrentes) distorce o resultado.",
        "O LPA usa as ações em circulação na data-base, não a média ponderada do período.",
    ]
    if data.company.accounting_template == "bank":
        limitations.append(
            "Graham formulou o critério para empresas não financeiras. Em bancos o patrimônio "
            "é alavancado e regulado: leia o resultado junto com ROE, Basileia e qualidade "
            "da carteira."
        )
    margins = config.valuation.margins_of_safety
    return ValuationResult(
        method=METHOD,
        ticker=ticker,
        reference_date=data.reference_date,
        applicable=True,
        formula=FORMULA,
        inputs={"eps": eps, "bvps": bvps, "price": price},
        assumptions=[
            {
                "name": "graham_constant",
                "value": GRAHAM_CONSTANT,
                "justification": "P/L máximo de 15 × P/VP máximo de 1,5 (Graham, The "
                "Intelligent Investor, critérios para o investidor defensivo).",
            },
            {
                "name": "margins_of_safety",
                "value": ", ".join(f"{m}" for m in margins) or "nenhuma",
                "unit": "ratio",
                "justification": "Margens definidas pelo investidor em config/defaults.yaml.",
            },
        ],
        result={
            "fair_value": fair_value,
            "ceiling_prices": ceiling_prices(fair_value, margins),
            "margin_of_safety_at_price": margin_at_price(fair_value, price.value),
            "price": price.value,
        },
        limitations=limitations,
        applicability_rationale=rationale + " Ambos são positivos na data-base.",
        engine_version=__version__,
        computed_at=now,
    )
