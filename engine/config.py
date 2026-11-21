"""Investor analysis parameters loaded from `config/defaults.yaml`.

These are not secrets. Percentages are fractions (0.06 means 6%). A `None` value means
the parameter has not been decided yet; methods that depend on it must refuse to run.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from engine.settings import PROJECT_ROOT

DEFAULTS_PATH = PROJECT_ROOT / "config" / "defaults.yaml"


class _ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ValuationConfig(_ConfigModel):
    margin_of_safety: Decimal | None = Field(default=None, ge=0, lt=1)
    cost_of_equity: Decimal | None = Field(default=None, gt=0, lt=1)


class BazinConfig(_ConfigModel):
    target_dividend_yield: Decimal = Field(gt=0, lt=1)
    lookback_years: int | None = Field(default=None, ge=1)


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
