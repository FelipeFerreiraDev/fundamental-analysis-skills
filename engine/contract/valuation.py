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


class ValuationOutput(ContractModel):
    """Per-share results. Margins are fractions (0.25 means 25%)."""

    unit: Literal["BRL/share"] = "BRL/share"
    fair_value: Decimal | None = Field(
        default=None, description="Intrinsic value estimated by the method."
    )
    ceiling_price: Decimal | None = Field(
        default=None, description="Maximum purchase price (Bazin: the method's own result)."
    )
    required_margin_of_safety: Decimal | None = Field(
        default=None,
        ge=0,
        lt=1,
        description="Margin applied to fair_value to derive ceiling_price, when applicable.",
    )
    margin_of_safety_at_price: Decimal | None = Field(
        default=None, description="(fair_value - price) / fair_value at the snapshot price."
    )

    @model_validator(mode="after")
    def _check_has_result(self) -> ValuationOutput:
        if self.fair_value is None and self.ceiling_price is None:
            raise ValueError("a valuation result needs a fair_value or a ceiling_price")
        return self


class ValuationResult(ContractModel):
    schema_version: Literal["0.2.0"] = SCHEMA_VERSION
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
