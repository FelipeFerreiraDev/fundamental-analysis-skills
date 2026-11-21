"""Indicators, Graham and Bazin on synthetic snapshots with hand-checked results."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from engine.config import load_config
from engine.contract import AnalysisData
from engine.indicators.core import (
    IndicatorError,
    adjusted_cash_events,
    compute_indicators,
    equity_at,
    ltm_flow,
    shift_years,
)
from engine.valuation.bazin import value_bazin
from engine.valuation.common import ceiling_prices, margin_at_price
from engine.valuation.graham import graham_number, value_graham
from tests.factories import SOURCE, reported

AS_OF = datetime(2026, 11, 21, 12, 0)
CONFIG = load_config()


def _flow(value, start, end, period_type):
    return reported(value, period={"type": period_type, "start": start, "end": end})


def _balance(value, end, **kw):
    return reported(value, period={"type": "INSTANT", "end": end}, **kw)


def _action(kind, record, value=None, factor=None, payment=None, label=None):
    return {
        "ticker": "TEST3",
        "action_type": kind,
        "source_label": label or kind.upper(),
        "record_date": record,
        "payment_date": payment,
        "value_per_share": Decimal(value) if value else None,
        "factor": Decimal(factor) if factor else None,
        "source_ids": [SOURCE["id"]],
    }


def _data(*, price="20", shares="100", actions=None, **financials) -> AnalysisData:
    defaults = {
        "net_income": [
            _flow("90", date(2025, 1, 1), date(2025, 12, 31), "FY"),
            _flow("60", date(2025, 1, 1), date(2025, 9, 30), "YTD"),
            _flow("50", date(2026, 1, 1), date(2026, 9, 30), "YTD"),
        ],
        "equity": [_balance("1000", date(2026, 9, 30)), _balance("900", date(2025, 9, 30))],
    }
    defaults.update(financials)
    return AnalysisData(
        company={
            "name": "Empresa Teste S.A.",
            "cnpj": "12345678000199",
            "cvm_code": 1,
            "accounting_template": "non_financial",
            "sector": "industrial",
            "securities": [{"ticker": "TEST3", "share_class": "ON"}],
        },
        reference_date=date(2026, 9, 30),
        as_of=AS_OF,
        ingestion_run_ids=["r"],
        market={
            "prices": {
                "TEST3": reported(
                    price,
                    "BRL/share",
                    period={"type": "INSTANT", "end": date(2026, 11, 20)},
                    basis=None,
                )
            },
            "shares_outstanding": {
                "TEST3": reported(
                    shares,
                    "shares",
                    period={"type": "INSTANT", "end": date(2026, 9, 30)},
                    basis=None,
                )
            },
        },
        financials=defaults,
        corporate_actions=actions
        if actions is not None
        else [
            _action("dividend", date(2020, 5, 4), "4"),  # outside the 5-year window
            _action("dividend", date(2022, 5, 2), "2"),  # before the 2-for-1 split: 1 per share now
            _action("split", date(2024, 4, 15), factor="2"),
            _action("jcp", date(2025, 12, 1), "1", payment=date(2025, 12, 20)),  # 15%
            _action("jcp", date(2026, 3, 2), "1", payment=date(2026, 3, 11)),  # 17.5%
            _action("other", date(2026, 3, 2), "0.1", label="RENDIMENTO"),
        ],
        sources=[SOURCE],
    )


class TestIndicators:
    def test_ltm_from_year_to_date(self):
        ltm = ltm_flow(_data(), "net_income")
        assert ltm.value == Decimal("80")  # 50 + 90 - 60
        assert (ltm.period.start, ltm.period.end) == (date(2025, 10, 1), date(2026, 9, 30))
        assert ltm.nature == "derived"

    def test_ltm_requires_comparable_periods(self):
        data = _data(net_income=[_flow("50", date(2026, 1, 1), date(2026, 9, 30), "YTD")])
        with pytest.raises(IndicatorError, match="faltam"):
            ltm_flow(data, "net_income")

    def test_equity_derived_from_total_minus_minorities(self):
        data = _data(
            equity=[],
            equity_total=[_balance("1100", date(2026, 9, 30))],
            non_controlling_interests=[_balance("100", date(2026, 9, 30))],
        )
        equity = equity_at(data, date(2026, 9, 30))
        assert (equity.value, equity.nature) == (Decimal("1000"), "derived")

    def test_cash_events_adjusted_for_split_and_taxed_by_payment_date(self):
        events = adjusted_cash_events(_data(), "TEST3", CONFIG.bazin)
        by_date = {(e.action.record_date, e.action.action_type): e for e in events}

        old = by_date[(date(2022, 5, 2), "dividend")]
        assert (old.adjustment_factor, old.gross, old.net) == (Decimal(2), Decimal(1), Decimal(1))
        assert by_date[(date(2025, 12, 1), "jcp")].net == Decimal("0.85")
        assert by_date[(date(2026, 3, 2), "jcp")].net == Decimal("0.825")

    def test_report(self):
        report = compute_indicators(_data(), "TEST3", CONFIG.bazin, now=AS_OF)
        v = report.values
        assert v["eps_ltm"].value == Decimal("0.8")  # 80 / 100
        assert v["bvps"].value == Decimal("10")  # 1000 / 100
        assert v["roe_ltm"].value == Decimal("80") / Decimal("950")
        assert v["pe_ratio"].value == Decimal("25")  # 20 / 0.8
        assert v["pb_ratio"].value == Decimal("2")
        assert v["dividends_per_share_ltm_gross"].value == Decimal("2.1")  # 1 + 1 + 0.1
        assert v["dividends_per_share_ltm_net"].value == Decimal("1.775")  # 0.85 + 0.825 + 0.1
        assert v["dividend_yield_ltm_gross"].value == Decimal("0.105")
        annual = {
            x.period.end.year: x.value for x in report.series["dividends_per_share_annual_gross"]
        }
        assert annual == {2020: Decimal("2"), 2022: Decimal("1"), 2025: Decimal("1")}
        assert report.unavailable == {}

    def test_multiples_unavailable_with_losses(self):
        data = _data(
            net_income=[
                _flow("-90", date(2025, 1, 1), date(2025, 12, 31), "FY"),
                _flow("10", date(2025, 1, 1), date(2025, 9, 30), "YTD"),
                _flow("5", date(2026, 1, 1), date(2026, 9, 30), "YTD"),
            ]
        )
        report = compute_indicators(data, "TEST3", CONFIG.bazin, now=AS_OF)
        assert "pe_ratio" in report.unavailable

    def test_shift_years_handles_leap_day(self):
        assert shift_years(date(2024, 2, 29), -1) == date(2023, 2, 28)


class TestGraham:
    def test_formula(self):
        assert graham_number(Decimal("2"), Decimal("10")) == Decimal(450).sqrt()
        with pytest.raises(ValueError):
            graham_number(Decimal("-1"), Decimal("10"))

    def test_ceilings_and_margin(self):
        assert [
            c.price for c in ceiling_prices(Decimal("100"), [Decimal("0.25"), Decimal("0.15")])
        ] == [
            Decimal("85.0000"),
            Decimal("75.0000"),
        ]
        assert margin_at_price(Decimal("100"), Decimal("60")) == Decimal("0.4000")

    def test_result(self):
        data = _data()
        indicators = compute_indicators(data, "TEST3", CONFIG.bazin, now=AS_OF)
        result = value_graham(data, indicators, "TEST3", CONFIG, now=AS_OF)

        expected = (
            (Decimal("22.5") * Decimal("0.8") * Decimal("10")).sqrt().quantize(Decimal("0.0001"))
        )
        assert result.applicable
        assert result.result.fair_value == expected  # √180 = 13.4164
        assert [
            c.margin_of_safety for c in result.result.ceiling_prices
        ] == CONFIG.valuation.margins_of_safety
        assert result.inputs["eps"].value == Decimal("0.8")

    def test_not_applicable_with_negative_eps(self):
        data = _data(
            net_income=[
                _flow("-90", date(2025, 1, 1), date(2025, 12, 31), "FY"),
                _flow("10", date(2025, 1, 1), date(2025, 9, 30), "YTD"),
                _flow("5", date(2026, 1, 1), date(2026, 9, 30), "YTD"),
            ]
        )
        indicators = compute_indicators(data, "TEST3", CONFIG.bazin, now=AS_OF)
        result = value_graham(data, indicators, "TEST3", CONFIG, now=AS_OF)
        assert not result.applicable
        assert "LPA" in result.not_applicable_reason


class TestBazin:
    def test_gross_and_net_ceilings(self):
        data = _data()
        indicators = compute_indicators(data, "TEST3", CONFIG.bazin, now=AS_OF)
        gross = value_bazin(data, indicators, "TEST3", CONFIG, net=False, now=AS_OF)
        net = value_bazin(data, indicators, "TEST3", CONFIG, net=True, now=AS_OF)

        # window 2021-11-22..2026-11-21: 1 (2022, adjusted) + 1 + 1 + 0.1 = 3.1 over 5 years
        assert gross.inputs["average_dividends_per_share"].value == Decimal("0.62")
        assert gross.result.ceiling_price == Decimal("10.3333")  # 0.62 / 0.06
        assert net.inputs["average_dividends_per_share"].value == Decimal("0.555")  # 2.775 / 5
        assert net.result.ceiling_price == Decimal("9.2500")
        assert any("12 meses sem nenhum provento" in item for item in gross.limitations)
        assert gross.method == "bazin_gross" and net.method == "bazin_net"

    def test_not_applicable_when_history_is_shorter_than_window(self):
        data = _data(actions=[_action("dividend", date(2025, 5, 2), "1")])
        indicators = compute_indicators(data, "TEST3", CONFIG.bazin, now=AS_OF)
        result = value_bazin(data, indicators, "TEST3", CONFIG, net=False, now=AS_OF)
        assert not result.applicable
        assert "começa em 2025-05-02" in result.not_applicable_reason

    def test_not_applicable_without_cash_events(self):
        data = _data(actions=[])
        indicators = compute_indicators(data, "TEST3", CONFIG.bazin, now=AS_OF)
        assert "dividends" in indicators.unavailable
        result = value_bazin(data, indicators, "TEST3", CONFIG, net=False, now=AS_OF)
        assert not result.applicable
