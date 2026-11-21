from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal

import pytest

from engine.contract import AnalysisData
from engine.contract.validation import ValidationReport
from engine.indicators.rates import compound
from engine.ingest import macro
from engine.ingest.market_sync import sync_macro
from engine.snapshot.build import SnapshotError, build_snapshot, write_snapshot
from engine.validation import checks
from tests.b3_files import write_json
from tests.factories import SOURCE, instant, reported
from tests.test_ingest_market import SGS, TODAY, _market, synced  # noqa: F401 (fixture)

AS_OF = datetime(2026, 11, 21, 12, 0)


def test_compound_rates():
    assert compound([Decimal("0.01"), Decimal("0.02")]) == Decimal("0.0302")
    assert compound([]) == 0
    with pytest.raises(ValueError):
        compound([Decimal("-1")])


@pytest.fixture
def full_db(synced, tmp_path):  # noqa: F811
    conn, fetcher = synced
    _market(conn, fetcher)
    months = [{"data": f"01/{m:02d}/2026", "valor": "0.5"} for m in range(1, 11)]
    months = [
        {"data": "01/11/2025", "valor": "0.5"},
        {"data": "01/12/2025", "valor": "0.5"},
    ] + months
    for start, end in macro.sgs_windows(date(2025, 1, 1), TODAY):
        fetcher.files[macro.sgs_url(SGS, 432, start, end)] = write_json(
            tmp_path / f"selic{start.year}.json", [{"data": "20/11/2026", "valor": "13.75"}]
        )
        fetcher.files[macro.sgs_url(SGS, 433, start, end)] = write_json(
            tmp_path / f"ipca{start.year}.json", months if start.year == 2025 else []
        )
    sync_macro(conn, sgs_base_url=SGS, fetcher=fetcher, years=2, today=TODAY)
    return conn


class TestSnapshot:
    def test_builds_a_traceable_snapshot(self, full_db, tmp_path):
        data = build_snapshot(full_db, "TEST3", as_of=AS_OF)

        assert data.reference_date == date(2026, 6, 30)
        assert data.company.accounting_template == "bank"
        price = data.market.prices["TEST3"]
        assert price.value == Decimal("14.3")  # brapi quote is newer than the last close
        assert price.source_ids[0].startswith("brapi-quote-")
        shares = data.market.shares_outstanding["TEST3"]
        assert (shares.value, shares.nature) == (Decimal("990"), "derived")
        assert [v.value for v in data.financials["net_income"]] == [
            Decimal("900000.0000"),
            Decimal("900000.0000"),
            Decimal("2000500.0000"),
        ]
        assert {s.id for s in data.sources} >= {"cvm-dfp-2025-12-31-v1", "cvm-itr-2026-06-30-v1"}
        assert data.macro["selic_target"][0].value == Decimal("0.1375")
        ipca = data.macro["ipca_12m"][0]
        assert ipca.value == compound([Decimal("0.005")] * 12)
        assert (ipca.period.type, ipca.period.end) == ("LTM", date(2026, 10, 31))
        assert {a.action_type for a in data.corporate_actions} >= {"jcp", "split"}

    def test_written_file_round_trips(self, full_db, tmp_path):
        data = build_snapshot(full_db, "TEST3", as_of=AS_OF)
        path = write_snapshot(data, "test3", root=tmp_path)

        assert path == tmp_path / "TEST3" / "2026-06-30" / "data.json"
        loaded = AnalysisData.model_validate_json(path.read_text(encoding="utf-8"))
        assert loaded == data
        assert json.loads(path.read_text())["market"]["prices"]["TEST3"]["value"] == "14.3000"

    def test_unknown_ticker(self, full_db):
        with pytest.raises(SnapshotError):
            build_snapshot(full_db, "NOPE3")

    def test_validation_blocks_when_history_is_short(self, full_db):
        data = build_snapshot(full_db, "TEST3", as_of=AS_OF)
        report = checks.run_validation(data, full_db, "TEST3", now=AS_OF)

        required = next(c for c in report.checks if c.id == "required_inputs")
        assert not required.passed
        assert any("lucro líquido anual" in d for d in required.details)
        assert report.blocking
        ValidationReport.model_validate_json(report.model_dump_json())


def _data(**financials) -> AnalysisData:
    return AnalysisData(
        company={
            "name": "Empresa Teste S.A.",
            "cnpj": "12345678000199",
            "cvm_code": 1,
            "accounting_template": "non_financial",
            "sector": "industrial",
            "securities": [{"ticker": "TEST3", "share_class": "ON"}],
        },
        reference_date=date(2025, 12, 31),
        as_of=AS_OF,
        ingestion_run_ids=["r"],
        market={
            "prices": {"TEST3": instant("10", "BRL/share")},
            "shares_outstanding": {"TEST3": instant("100", "shares")},
        },
        financials=financials,
        sources=[SOURCE],
    )


def _flow(value, start, end, period_type):
    return reported(value, period={"type": period_type, "start": start, "end": end})


class TestChecks:
    def test_balance_sheet_mismatch_is_an_error(self):
        check = checks.check_balance_sheet_identity(
            _data(
                total_assets=[instant("100", "BRL", basis="consolidated")],
                total_liabilities_and_equity=[instant("99", "BRL", basis="consolidated")],
            )
        )
        assert (check.passed, check.severity) == (False, "error")

    def test_quarter_must_match_ytd_difference(self):
        series = [
            _flow("10", date(2025, 1, 1), date(2025, 3, 31), "YTD"),
            _flow("25", date(2025, 1, 1), date(2025, 6, 30), "YTD"),
            _flow("15", date(2025, 4, 1), date(2025, 6, 30), "3M"),
        ]
        assert checks.check_quarter_consistency(_data(net_income=series)).passed
        series[2] = _flow("14", date(2025, 4, 1), date(2025, 6, 30), "3M")
        failed = checks.check_quarter_consistency(_data(net_income=series))
        assert not failed.passed and failed.severity == "warning"

    def test_zero_annual_flow_is_flagged(self):
        check = checks.check_zero_flows(
            _data(service_fee_revenue=[_flow("0", date(2019, 1, 1), date(2019, 12, 31), "FY")])
        )
        assert not check.passed

    def test_stale_price(self):
        data = _data()
        stale = data.model_copy(update={"as_of": datetime(2026, 2, 1)})
        assert not checks.check_price_freshness(stale).passed

    def test_report_blocking_must_match_checks(self):
        with pytest.raises(ValueError, match="blocking"):
            ValidationReport(
                ticker="TEST3",
                reference_date=date(2025, 12, 31),
                snapshot_as_of=AS_OF,
                generated_at=AS_OF,
                engine_version="0",
                checks=[{"id": "x", "severity": "error", "passed": False, "message": "falhou"}],
                blocking=False,
            )
