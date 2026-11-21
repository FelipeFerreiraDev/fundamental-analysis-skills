"""`data.json`: the snapshot of one company that every specialist reads."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from engine.contract.common import (
    SCHEMA_VERSION,
    SNAKE_CASE,
    TICKER,
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


class CorporateAction(ContractModel):
    """A cash distribution or share event exactly as published by B3 (no adjustment)."""

    ticker: str = Field(pattern=TICKER)
    action_type: Literal["dividend", "jcp", "split", "reverse_split", "bonus_shares", "other"]
    source_label: str = Field(description="Label as published, e.g. JRS CAP PROPRIO.")
    declared_at: date | None = None
    record_date: date = Field(description="Data-com: last day with the right to the event.")
    payment_date: date | None = None
    value_per_share: Decimal | None = Field(default=None, description="BRL per share (cash).")
    is_gross: bool | None = Field(default=None, description="JCP: value before withholding tax.")
    factor: Decimal | None = Field(default=None, description="New shares per old share.")
    related_to: str | None = None
    source_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def _check_kind(self) -> CorporateAction:
        share_event = self.action_type in ("split", "reverse_split", "bonus_shares")
        if share_event and (self.factor is None or self.factor <= 0):
            raise ValueError(f"{self.action_type} requires a positive factor")
        if not share_event and self.value_per_share is None:
            raise ValueError(f"{self.action_type} requires value_per_share")
        return self


class AnalysisData(ContractModel):
    schema_version: Literal["0.2.0"] = SCHEMA_VERSION
    company: Company
    reference_date: date = Field(description="Date of the latest financial statements used.")
    as_of: datetime = Field(description="When the snapshot was taken from the local database.")
    ingestion_run_ids: list[str] = Field(min_length=1)
    market: MarketData
    financials: dict[str, list[FinancialValue]] = Field(
        description="Canonical concept (snake_case) -> time series of values."
    )
    macro: dict[str, list[FinancialValue]] = Field(default_factory=dict)
    corporate_actions: list[CorporateAction] = Field(
        default_factory=list, description="Dividends, JCP and share events, unadjusted."
    )
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
        unknown = sorted({a.ticker for a in self.corporate_actions} - tickers)
        if unknown:
            raise ValueError(f"corporate_actions has tickers not in company: {unknown}")

        for group in (self.financials, self.macro):
            bad_keys = [key for key in group if not _SNAKE_CASE.match(key)]
            if bad_keys:
                raise ValueError(f"concept names must be snake_case: {bad_keys}")

        for concept, series in self.financials.items():
            if any(value.basis is None for value in series):
                raise ValueError(f"financials.{concept} has values without basis")

        known = set(source_ids)
        referenced = [sid for value in self._all_values() for sid in value.source_ids]
        referenced += [sid for action in self.corporate_actions for sid in action.source_ids]
        missing = sorted({sid for sid in referenced if sid not in known})
        if missing:
            raise ValueError(f"values reference unknown source ids: {missing}")
        return self

    def _all_values(self) -> list[FinancialValue]:
        values = [*self.market.prices.values(), *self.market.shares_outstanding.values()]
        for group in (self.financials, self.macro):
            for series in group.values():
                values.extend(series)
        return values
