"""Investor analysis parameters loaded from `config/defaults.yaml`.

These are not secrets. Percentages are fractions (0.06 means 6%). A `None` value means
the parameter has not been decided yet; methods that depend on it must refuse to run.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from engine.settings import PROJECT_ROOT

DEFAULTS_PATH = PROJECT_ROOT / "config" / "defaults.yaml"


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ValuationConfig(_ConfigModel):
    margins_of_safety: list[Decimal] = Field(default_factory=list)
    cost_of_equity: Decimal | None = Field(default=None, gt=0, lt=1)

    @field_validator("margins_of_safety")
    @classmethod
    def _check_margins(cls, margins: list[Decimal]) -> list[Decimal]:
        if any(not 0 <= m < 1 for m in margins):
            raise ValueError("margins of safety must be fractions in [0, 1)")
        if len(set(margins)) != len(margins):
            raise ValueError("margins of safety must not repeat")
        return sorted(margins)


class WithholdingRate(_ConfigModel):
    since: date
    rate: Decimal = Field(ge=0, lt=1)


class BazinConfig(_ConfigModel):
    target_dividend_yield: Decimal = Field(gt=0, lt=1)
    lookback_years: int | None = Field(default=None, ge=1)
    include_jcp_correction: bool = True
    jcp_withholding_rates: list[WithholdingRate] = Field(default_factory=list)

    @field_validator("jcp_withholding_rates")
    @classmethod
    def _sorted_rates(cls, rates: list[WithholdingRate]) -> list[WithholdingRate]:
        ordered = sorted(rates, key=lambda r: r.since)
        if len({r.since for r in ordered}) != len(ordered):
            raise ValueError("withholding rates must have distinct start dates")
        return ordered

    def jcp_rate_on(self, day: date) -> Decimal:
        """Withholding rate in force on `day` (payment date of the JCP)."""
        applicable = [r for r in self.jcp_withholding_rates if r.since <= day]
        if not applicable:
            raise ValueError(f"no JCP withholding rate configured for {day}")
        return applicable[-1].rate


class SyncConfig(_ConfigModel):
    history_years: int = Field(ge=1, le=20)
    quarterly_years: int = Field(ge=1, le=10)


class AnalysisConfig(_ConfigModel):
    valuation: ValuationConfig
    bazin: BazinConfig
    sync: SyncConfig


def load_config(path: Path = DEFAULTS_PATH) -> AnalysisConfig:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return AnalysisConfig.model_validate(raw)


SECTOR_OVERRIDES_PATH = PROJECT_ROOT / "config" / "sector_overrides.yaml"


def load_sector_overrides(path: Path = SECTOR_OVERRIDES_PATH) -> dict[str, str]:
    """Ticker -> sector profile chosen by the investor when the CVM mapping does not fit."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {str(ticker).upper(): str(profile) for ticker, profile in raw.items()}
