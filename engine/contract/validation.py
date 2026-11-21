"""`validation.json`: result of the data checks that run before any valuation."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from engine.contract.common import SCHEMA_VERSION, SNAKE_CASE, TICKER, ContractModel


class Check(ContractModel):
    id: str = Field(pattern=SNAKE_CASE)
    severity: Literal["info", "warning", "error"]
    passed: bool
    message: str = Field(min_length=1, description="Summary for the investor (Portuguese).")
    details: list[str] = Field(default_factory=list)


class ValidationReport(ContractModel):
    schema_version: Literal["0.3.0"] = SCHEMA_VERSION
    ticker: str = Field(pattern=TICKER)
    reference_date: date
    snapshot_as_of: datetime
    generated_at: datetime
    engine_version: str
    checks: list[Check] = Field(min_length=1)
    blocking: bool = Field(description="True when an error check failed: no valuation may run.")

    @model_validator(mode="after")
    def _check_blocking(self) -> ValidationReport:
        expected = any(c.severity == "error" and not c.passed for c in self.checks)
        if self.blocking != expected:
            raise ValueError("blocking must be true exactly when an error check failed")
        return self
