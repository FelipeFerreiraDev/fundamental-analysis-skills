"""Helpers shared by the valuation methods."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from engine import __version__
from engine.contract import ValuationResult
from engine.contract.valuation import CeilingPrice

PRICE_PLACES = Decimal("0.0001")


def ceiling_prices(fair_value: Decimal, margins: list[Decimal]) -> list[CeilingPrice]:
    """Ceiling price for each margin of safety: fair_value x (1 - margin)."""
    return [
        CeilingPrice(margin_of_safety=m, price=(fair_value * (1 - m)).quantize(PRICE_PLACES))
        for m in sorted(margins)
    ]


def margin_at_price(fair_value: Decimal, price: Decimal) -> Decimal:
    """Discount of the price to the fair value: (fair_value - price) / fair_value."""
    if fair_value <= 0:
        raise ValueError("fair value must be positive")
    return ((fair_value - price) / fair_value).quantize(PRICE_PLACES)


def not_applicable(
    method: str, ticker: str, reference_date, reason: str, rationale: str, now: datetime
) -> ValuationResult:
    return ValuationResult(
        method=method,
        ticker=ticker,
        reference_date=reference_date,
        applicable=False,
        not_applicable_reason=reason,
        applicability_rationale=rationale,
        engine_version=__version__,
        computed_at=now,
    )
