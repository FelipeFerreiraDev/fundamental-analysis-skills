"""`data.json`: the snapshot of one company that every specialist reads."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import Field, model_validator

from engine.contract.common import (
    SCHEMA_VERSION,
    SNAKE_CASE,
    Company,
    ContractModel,
    FinancialValue,
    Source,
)

_SNAKE_CASE = re.compile(SNAKE_CASE)


class MarketData(ContractModel):
    prices: dict[str, FinancialValue] = Field(description="Ticker -> price (BRL/share, INSTANT).")
    shares_outstanding: dict[str, FinancialValue] = Field(
        description="Ticker -> shares outstanding excluding treasury shares (shares, INSTANT)."
    )

    @model_validator(mode="after")
    def _check_units(self) -> MarketData:
        for ticker, price in self.prices.items():
            if price.unit != "BRL/share" or price.period.type != "INSTANT":
                raise ValueError(f"price of {ticker} must be BRL/share at an INSTANT")
        for ticker, shares in self.shares_outstanding.items():
            if shares.unit != "shares" or shares.period.type != "INSTANT":
                raise ValueError(f"shares outstanding of {ticker} must be shares at an INSTANT")
        return self


class AnalysisData(ContractModel):
    schema_version: Literal["0.1.0"] = SCHEMA_VERSION
    company: Company
    reference_date: date = Field(description="Date of the latest financial statements used.")
    as_of: datetime = Field(description="When the snapshot was taken from the local database.")
    ingestion_run_ids: list[str] = Field(min_length=1)
    market: MarketData
    financials: dict[str, list[FinancialValue]] = Field(
        description="Canonical concept (snake_case) -> time series of values."
    )
    macro: dict[str, list[FinancialValue]] = Field(default_factory=dict)
    sources: list[Source] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_integrity(self) -> AnalysisData:
        source_ids = [source.id for source in self.sources]
        duplicated = sorted({sid for sid in source_ids if source_ids.count(sid) > 1})
        if duplicated:
            raise ValueError(f"duplicated source ids: {duplicated}")

        tickers = {security.ticker for security in self.company.securities}
        for field_name in ("prices", "shares_outstanding"):
            unknown = sorted(set(getattr(self.market, field_name)) - tickers)
            if unknown:
                raise ValueError(f"market.{field_name} has tickers not in company: {unknown}")

        for group in (self.financials, self.macro):
            bad_keys = [key for key in group if not _SNAKE_CASE.match(key)]
            if bad_keys:
                raise ValueError(f"concept names must be snake_case: {bad_keys}")

        for concept, series in self.financials.items():
            if any(value.basis is None for value in series):
                raise ValueError(f"financials.{concept} has values without basis")

        known = set(source_ids)
        missing = sorted(
            {sid for value in self._all_values() for sid in value.source_ids if sid not in known}
        )
        if missing:
            raise ValueError(f"values reference unknown source ids: {missing}")
        return self

    def _all_values(self) -> list[FinancialValue]:
        values = [*self.market.prices.values(), *self.market.shares_outstanding.values()]
        for group in (self.financials, self.macro):
            for series in group.values():
                values.extend(series)
        return values
