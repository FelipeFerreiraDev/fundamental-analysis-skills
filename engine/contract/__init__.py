"""Shared data contract between skills (docs/architecture.md §6).

The pydantic models here are the single source of truth. The JSON Schemas in `schemas/`
are generated from them with `skillsinvest export-schemas`.
"""

from engine.contract.analysis_data import AnalysisData, CorporateAction, MarketData
from engine.contract.common import (
    SCHEMA_VERSION,
    Company,
    FinancialValue,
    Period,
    Security,
    Source,
)
from engine.contract.valuation import Assumption, ValuationOutput, ValuationResult

__all__ = [
    "SCHEMA_VERSION",
    "AnalysisData",
    "Assumption",
    "Company",
    "CorporateAction",
    "FinancialValue",
    "MarketData",
    "Period",
    "Security",
    "Source",
    "ValuationOutput",
    "ValuationResult",
]
