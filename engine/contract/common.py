"""Building blocks of the data contract: periods, traceable values, sources and companies."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "0.2.0"

PeriodType = Literal["INSTANT", "3M", "YTD", "FY", "LTM"]
Unit = Literal["BRL", "BRL/share", "shares", "ratio", "count"]
Basis = Literal["consolidated", "individual", "prudential", "managerial"]
Nature = Literal["reported", "derived", "estimated"]
Confidence = Literal["high", "medium", "low"]
AccountingTemplate = Literal["non_financial", "bank", "insurance"]
ShareClass = Literal["ON", "PN", "PNA", "PNB", "UNIT"]
Provider = Literal["cvm", "company_ri", "b3", "brapi", "bcb", "tesouro"]
Extraction = Literal["structured", "llm_pdf"]
SectorProfile = Literal[
    "banking",
    "insurance",
    "real-estate",
    "fii",
    "utilities",
    "infrastructure",
    "retail",
    "consumer",
    "industrial",
    "commodities",
    "healthcare",
    "tmt",
    "education",
    "holdings",
]

SNAKE_CASE = r"^[a-z][a-z0-9_]*$"
TICKER = r"^[A-Z]{4}[0-9]{1,2}$"

# Inclusive day counts accepted for each period type. They catch the classic error of
# labelling a year-to-date value as a quarter (or the reverse).
_PERIOD_DAYS: dict[str, tuple[int, int]] = {
    "3M": (88, 93),
    "YTD": (1, 367),
    "FY": (364, 367),
    "LTM": (364, 367),
}


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(ContractModel):
    """Reference period of a value. Balance sheet items are INSTANT and have no start."""

    type: PeriodType
    start: date | None = None
    end: date

    @model_validator(mode="after")
    def _check_bounds(self) -> Period:
        if self.type == "INSTANT":
            if self.start is not None:
                raise ValueError("INSTANT period must not have a start date")
            return self
        if self.start is None:
            raise ValueError(f"{self.type} period requires a start date")
        if self.start > self.end:
            raise ValueError("period start must not be after its end")
        days = (self.end - self.start).days + 1
        low, high = _PERIOD_DAYS[self.type]
        if not low <= days <= high:
            raise ValueError(
                f"{self.type} period spans {days} days; expected between {low} and {high}"
            )
        return self


class FinancialValue(ContractModel):
    """A single number with everything needed to trace and audit it."""

    value: Decimal
    unit: Unit
    period: Period
    basis: Basis | None = Field(
        default=None, description="Required for accounting data; null for market and macro data."
    )
    nature: Nature
    source_ids: list[str] = Field(default_factory=list)
    confidence: Confidence
    note: str | None = Field(
        default=None,
        description="How a derived value was computed, or why an estimate was chosen.",
    )

    @model_validator(mode="after")
    def _check_traceability(self) -> FinancialValue:
        if self.nature in ("reported", "derived") and not self.source_ids:
            raise ValueError(f"{self.nature} values must reference at least one source")
        if self.nature in ("derived", "estimated") and not (self.note and self.note.strip()):
            raise ValueError(f"{self.nature} values must explain how they were obtained in 'note'")
        return self


class Source(ContractModel):
    """A document or dataset a value came from. PDF extractions cite one page per source."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    provider: Provider
    document_type: str = Field(min_length=1, description="e.g. DFP, ITR, COTAHIST, quote, SGS")
    title: str | None = None
    url: str | None = Field(default=None, pattern=r"^https?://")
    published_at: date | None = None
    retrieved_at: datetime
    version: int | None = Field(default=None, ge=1)
    page: int | None = Field(default=None, ge=1)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    extraction: Extraction

    @model_validator(mode="after")
    def _check_pdf_citation(self) -> Source:
        if self.extraction == "llm_pdf" and (self.url is None or self.page is None):
            raise ValueError("values extracted from PDFs must cite the document url and page")
        return self


class Security(ContractModel):
    ticker: str = Field(pattern=TICKER)
    share_class: ShareClass


class Company(ContractModel):
    name: str = Field(min_length=1)
    cnpj: str = Field(pattern=r"^[0-9]{14}$", description="Digits only.")
    cvm_code: int = Field(ge=1)
    accounting_template: AccountingTemplate
    sector: SectorProfile
    securities: list[Security] = Field(min_length=1)
