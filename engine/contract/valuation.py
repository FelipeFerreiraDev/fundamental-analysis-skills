"""`valuations/<method>.json`: common output format of every quantitative valuation method."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from engine.contract.common import (
    SCHEMA_VERSION,
    SNAKE_CASE,
    TICKER,
    ContractModel,
    FinancialValue,
    Unit,
)


class Assumption(ContractModel):
    name: str = Field(pattern=SNAKE_CASE)
    value: Decimal | str
    unit: Unit | None = None
    justification: str = Field(min_length=1)


class CeilingPrice(ContractModel):
    margin_of_safety: Decimal = Field(ge=0, lt=1)
    price: Decimal = Field(description="fair_value x (1 - margin_of_safety)")


class ValuationOutput(ContractModel):
    """Per-share results. Margins are fractions (0.25 means 25%)."""

    unit: Literal["BRL/share"] = "BRL/share"
    fair_value: Decimal | None = Field(
        default=None, description="Intrinsic value estimated by the method."
    )
    ceiling_price: Decimal | None = Field(
        default=None,
        description="Maximum purchase price given directly by the method (e.g. Bazin).",
    )
    ceiling_prices: list[CeilingPrice] = Field(
        default_factory=list,
        description="Ceiling price for each configured margin of safety (fair-value methods).",
    )
    margin_of_safety_at_price: Decimal | None = Field(
        default=None, description="(fair_value - price) / fair_value at the snapshot price."
    )
    price: Decimal | None = Field(default=None, description="Price the result was compared to.")

    @model_validator(mode="after")
    def _check_has_result(self) -> ValuationOutput:
        if self.fair_value is None and self.ceiling_price is None:
            raise ValueError("a valuation result needs a fair_value or a ceiling_price")
        if self.ceiling_prices and self.fair_value is None:
            raise ValueError("ceiling_prices are derived from fair_value")
        margins = [c.margin_of_safety for c in self.ceiling_prices]
        if margins != sorted(set(margins)):
            raise ValueError("ceiling_prices must have distinct margins in ascending order")
        return self


class ValuationResult(ContractModel):
    schema_version: Literal["0.3.0"] = SCHEMA_VERSION
    method: str = Field(pattern=SNAKE_CASE, description="e.g. graham_number, bazin")
    ticker: str = Field(pattern=TICKER)
    reference_date: date
    applicable: bool
    not_applicable_reason: str | None = None
    formula: str | None = None
    inputs: dict[str, FinancialValue] = Field(default_factory=dict)
    assumptions: list[Assumption] = Field(default_factory=list)
    result: ValuationOutput | None = None
    limitations: list[str] = Field(default_factory=list)
    applicability_rationale: str = Field(min_length=1)
    engine_version: str
    computed_at: datetime

    @model_validator(mode="after")
    def _check_applicability(self) -> ValuationResult:
        if self.applicable:
            if self.not_applicable_reason is not None:
                raise ValueError("an applicable method must not have a not_applicable_reason")
            if not self.formula or self.result is None or not self.inputs:
                raise ValueError("an applicable method requires formula, inputs and result")
        else:
            if not (self.not_applicable_reason and self.not_applicable_reason.strip()):
                raise ValueError("a non-applicable method must explain why")
            if self.result is not None:
                raise ValueError("a non-applicable method must not report a result")
        return self
