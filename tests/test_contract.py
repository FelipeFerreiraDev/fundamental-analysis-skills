from __future__ import annotations

from datetime import date, datetime

import pytest
from pydantic import ValidationError

from engine.contract import AnalysisData, Company, FinancialValue, Period, Source, ValuationResult
from tests.factories import SOURCE, instant, reported


class TestPeriod:
    def test_instant_has_no_start(self):
        with pytest.raises(ValidationError, match="must not have a start"):
            Period(type="INSTANT", start=date(2025, 1, 1), end=date(2025, 12, 31))

    def test_flow_period_requires_start(self):
        with pytest.raises(ValidationError, match="requires a start"):
            Period(type="FY", end=date(2025, 12, 31))

    def test_start_after_end_is_rejected(self):
        with pytest.raises(ValidationError, match="must not be after"):
            Period(type="YTD", start=date(2025, 10, 1), end=date(2025, 9, 30))

    def test_year_to_date_labelled_as_quarter_is_rejected(self):
        with pytest.raises(ValidationError, match="3M period spans 273 days"):
            Period(type="3M", start=date(2025, 1, 1), end=date(2025, 9, 30))

    @pytest.mark.parametrize(
        ("start", "end"),
        [
            (date(2025, 1, 1), date(2025, 3, 31)),
            (date(2024, 1, 1), date(2024, 3, 31)),  # leap year
            (date(2025, 7, 1), date(2025, 9, 30)),
            (date(2025, 10, 1), date(2025, 12, 31)),
        ],
    )
    def test_calendar_quarters_are_accepted(self, start, end):
        Period(type="3M", start=start, end=end)

    def test_last_twelve_months(self):
        Period(type="LTM", start=date(2025, 10, 1), end=date(2026, 9, 30))


class TestFinancialValue:
    def test_reported_value_requires_source(self):
        with pytest.raises(ValidationError, match="at least one source"):
            FinancialValue(**reported("1", source_ids=[]))

    def test_derived_value_requires_explanation(self):
        with pytest.raises(ValidationError, match="explain how"):
            FinancialValue(**reported("1", nature="derived"))

    def test_estimated_value_requires_explanation_but_not_source(self):
        with pytest.raises(ValidationError, match="explain how"):
            FinancialValue(**reported("1", nature="estimated", source_ids=[]))
        value = FinancialValue(
            **reported("0.05", "ratio", nature="estimated", source_ids=[], note="premissa")
        )
        assert value.nature == "estimated"

    def test_unknown_fields_are_rejected(self):
        with pytest.raises(ValidationError):
            FinancialValue(**reported("1", currency="BRL"))


class TestSource:
    def test_pdf_extraction_must_cite_url_and_page(self):
        with pytest.raises(ValidationError, match="url and page"):
            Source(**{**SOURCE, "provider": "company_ri", "extraction": "llm_pdf"})
        Source(
            **{
                **SOURCE,
                "provider": "company_ri",
                "extraction": "llm_pdf",
                "url": "https://ri.example.com/release.pdf",
                "page": 12,
            }
        )


def _analysis(**overrides) -> dict:
    base = {
        "company": {
            "name": "Empresa Teste S.A.",
            "cnpj": "12345678000199",
            "cvm_code": 99999,
            "accounting_template": "non_financial",
            "sector": "industrial",
            "securities": [{"ticker": "TEST3", "share_class": "ON"}],
        },
        "reference_date": date(2025, 12, 31),
        "as_of": datetime(2026, 11, 21, 12, 0),
        "ingestion_run_ids": ["run-1"],
        "market": {
            "prices": {"TEST3": instant("10.50", "BRL/share")},
            "shares_outstanding": {"TEST3": instant("1000000", "shares")},
        },
        "financials": {"net_income": [reported("123456.78")]},
        "sources": [SOURCE],
    }
    return {**base, **overrides}


class TestAnalysisData:
    def test_valid_snapshot(self):
        data = AnalysisData(**_analysis())
        assert data.schema_version == "0.3.0"

    def test_unknown_source_reference_is_rejected(self):
        financials = {"net_income": [reported("1", source_ids=["missing"])]}
        with pytest.raises(ValidationError, match="unknown source ids"):
            AnalysisData(**_analysis(financials=financials))

    def test_accounting_values_require_basis(self):
        financials = {"net_income": [reported("1", basis=None)]}
        with pytest.raises(ValidationError, match="without basis"):
            AnalysisData(**_analysis(financials=financials))

    def test_concepts_are_snake_case(self):
        with pytest.raises(ValidationError, match="snake_case"):
            AnalysisData(**_analysis(financials={"NetIncome": [reported("1")]}))

    def test_market_tickers_must_belong_to_company(self):
        market = {
            "prices": {"OTHR3": instant("1", "BRL/share")},
            "shares_outstanding": {},
        }
        with pytest.raises(ValidationError, match="not in company"):
            AnalysisData(**_analysis(market=market))

    def test_price_unit_is_enforced(self):
        market = {"prices": {"TEST3": instant("1", "BRL")}, "shares_outstanding": {}}
        with pytest.raises(ValidationError, match="BRL/share"):
            AnalysisData(**_analysis(market=market))


def _valuation(**overrides) -> dict:
    base = {
        "method": "graham_number",
        "ticker": "TEST3",
        "reference_date": date(2025, 12, 31),
        "applicable": True,
        "formula": "sqrt(22.5 * eps * bvps)",
        "inputs": {"eps": reported("2", "BRL/share")},
        "result": {"fair_value": "20.00"},
        "applicability_rationale": "lucro e patrimônio positivos",
        "engine_version": "0.3.0",
        "computed_at": datetime(2026, 11, 21, 12, 0),
    }
    return {**base, **overrides}


class TestValuationResult:
    def test_applicable_result(self):
        assert ValuationResult(**_valuation()).result is not None

    def test_applicable_requires_formula_inputs_and_result(self):
        with pytest.raises(ValidationError, match="requires formula"):
            ValuationResult(**_valuation(formula=None))

    def test_not_applicable_requires_reason_and_no_result(self):
        with pytest.raises(ValidationError, match="explain why"):
            ValuationResult(**_valuation(applicable=False, result=None))
        with pytest.raises(ValidationError, match="must not report a result"):
            ValuationResult(**_valuation(applicable=False, not_applicable_reason="LPA negativo"))
        result = ValuationResult(
            **_valuation(applicable=False, result=None, not_applicable_reason="LPA negativo")
        )
        assert not result.applicable

    def test_result_needs_a_price(self):
        with pytest.raises(ValidationError, match="fair_value or a ceiling_price"):
            ValuationResult(**_valuation(result={}))


def test_bbas3_fixture_matches_contract(bbas3_company):
    company = Company(**bbas3_company)
    assert company.accounting_template == "bank"
    assert [s.ticker for s in company.securities] == ["BBAS3"]
