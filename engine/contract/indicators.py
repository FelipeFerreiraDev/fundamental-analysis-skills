"""`indicators.json`: indicators derived from the snapshot by the engine."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from engine.contract.common import SCHEMA_VERSION, SNAKE_CASE, TICKER, ContractModel, FinancialValue

_SNAKE_CASE = re.compile(SNAKE_CASE)


class IndicatorsReport(ContractModel):
    schema_version: Literal["0.3.0"] = SCHEMA_VERSION
    ticker: str = Field(pattern=TICKER)
    reference_date: date
    snapshot_as_of: datetime
    generated_at: datetime
    engine_version: str
    values: dict[str, FinancialValue] = Field(description="Point-in-time indicators.")
    series: dict[str, list[FinancialValue]] = Field(
        default_factory=dict, description="Historical series (e.g. dividends per share by year)."
    )
    unavailable: dict[str, str] = Field(
        default_factory=dict, description="Indicator -> reason it could not be computed."
    )

    @model_validator(mode="after")
    def _check(self) -> IndicatorsReport:
        names = [*self.values, *self.series, *self.unavailable]
        bad = [n for n in names if not _SNAKE_CASE.match(n)]
        if bad:
            raise ValueError(f"indicator names must be snake_case: {bad}")
        derived = [v for v in self.values.values()] + [v for s in self.series.values() for v in s]
        if any(v.nature == "reported" and not v.source_ids for v in derived):
            raise ValueError("indicators must reference their sources")
        return self
