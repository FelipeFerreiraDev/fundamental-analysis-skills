from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from engine.config import SyncConfig
from engine.db import connect, init_database
from engine.db.reference import read_cvm_sector_map
from engine.ingest import b3, macro
from engine.ingest.market_sync import sync_macro, sync_market
from engine.ingest.sync import TickerNotFoundError, sync_company
from tests.b3_files import (
    SUPPLEMENT,
    cash_item,
    cash_page,
    cotahist_line,
    write_cotahist,
    write_json,
)
from tests.test_ingest_cvm import BASE, TODAY, _fetcher

COTAHIST = "https://cotahist.test"
LISTED = "https://listed.test"
BRAPI = "https://brapi.test/api"
SGS = "https://sgs.test"


class TestCotahist:
    def test_prices_are_scaled_and_filtered(self, tmp_path):
        path = write_cotahist(
            tmp_path / "c.zip",
            [
                cotahist_line("20261118", "TEST3", 1412),
                cotahist_line("20261119", "TEST3", 143000, factor=1000),  # quoted per 1000
                cotahist_line("20261119", "TEST3", 99, market="070"),  # options market
                cotahist_line("20261119", "OTHR3", 500),
            ],
        )
        prices = b3.parse_cotahist(path, {"TEST3"})

        assert [(p.trade_date, p.close) for p in prices] == [
            (date(2026, 11, 18), Decimal("14.12")),
            (date(2026, 11, 19), Decimal("1.43")),
        ]
        assert prices[0].volume == Decimal("12345.00")
        assert prices[0].trades == 42
        assert prices[0].isin == "BRTESTACNOR1"

    def test_duplicated_quote_is_rejected(self, tmp_path):
        line = cotahist_line("20261118", "TEST3", 1412)
        path = write_cotahist(tmp_path / "c.zip", [line, line])
        with pytest.raises(b3.B3FormatError, match="duplicated"):
            b3.parse_cotahist(path, {"TEST3"})


class TestCorporateEvents:
    def test_cash_events_by_class_with_payment_dates(self):
        supplement = b3.parse_supplement(SUPPLEMENT)
        page = cash_page(
            [
                cash_item("JRS CAP PROPRIO", "0,10245643978", "01/09/2026", "10/08/2026"),
                cash_item("DIVIDENDO", "1.234,5", "11/03/2025", "20/02/2025"),
                cash_item("DIVIDENDO", "9,9", "11/03/2025", "20/02/2025", type_stock="PN"),
                cash_item("AMORTIZACAO", "1,0", "01/01/2020", "01/01/2020"),
            ]
        )
        events, skipped = b3.parse_cash_dividends([page], "ON", supplement)

        assert [(e.action_type, e.value_per_share) for e in events] == [
            ("jcp", Decimal("0.10245643978")),
            ("dividend", Decimal("1234.5")),
        ]
        assert events[0].payment_date == date(2026, 9, 11)
        assert events[0].related_to == "2º Trimestre/2026"
        assert events[1].payment_date is None
        assert skipped == ["AMORTIZACAO"]

    def test_stock_events_use_new_shares_per_old_share(self):
        supplement = b3.parse_supplement(SUPPLEMENT)
        events = b3.parse_stock_events(supplement, "BRTESTACNOR1", "ON")

        factors = {e.action_type: e.factor for e in events}
        assert factors == {
            "split": Decimal("2"),  # +100%
            "reverse_split": Decimal("0.001"),  # 1000 -> 1
            "bonus_shares": Decimal("1.1"),  # +10% (label with accent)
        }

    def test_supplement_without_trading_name_is_rejected(self):
        with pytest.raises(b3.B3FormatError):
            b3.parse_supplement([{}])


class TestMacro:
    def test_sgs_percent_to_fraction_and_future_days_dropped(self):
        payload = [
            {"data": "20/11/2026", "valor": "13.75"},
            {"data": "21/11/2026", "valor": "13.75"},
            {"data": "09/12/2026", "valor": "13.75"},
        ]
        points = macro.parse_sgs(payload, 432, until=date(2026, 11, 21))

        assert [(p.ref_date, p.value) for p in points] == [
            (date(2026, 11, 20), Decimal("0.1375")),
            (date(2026, 11, 21), Decimal("0.1375")),
        ]

    def test_sgs_windows_never_exceed_the_api_limit(self):
        windows = macro.sgs_windows(date(2017, 1, 1), date(2026, 11, 21))
        assert windows == [
            (date(2017, 1, 1), date(2021, 12, 31)),
            (date(2022, 1, 1), date(2026, 11, 21)),
        ]

    def test_brapi_quote(self):
        payload = {
            "results": [
                {
                    "symbol": "TEST3",
                    "currency": "BRL",
                    "regularMarketPrice": 14.3,
                    "regularMarketTime": "2026-11-20T21:30:00.000Z",
                }
            ]
        }
        quote = macro.parse_brapi_quote(payload, "TEST3")
        assert quote.price == Decimal("14.3")
        assert quote.quoted_at == datetime(2026, 11, 20, 21, 30)

    def test_brapi_error_payload_is_rejected(self):
        with pytest.raises(macro.MacroFormatError):
            macro.parse_brapi_quote({"error": True, "message": "plano"}, "TEST3")


@pytest.fixture
def synced(tmp_path):
    db_path = tmp_path / "w.duckdb"
    init_database(db_path)
    fetcher = _fetcher(tmp_path)
    with connect(db_path) as conn:
        sync_company(
            conn,
            "TEST3",
            cvm_base_url=BASE,
            config=SyncConfig(history_years=8, quarterly_years=1),
            fetcher=fetcher,
            sector_map=read_cvm_sector_map(),
            sector_overrides={},
            today=TODAY,
        )
        fetcher.files.update(
            {
                f"{COTAHIST}/COTAHIST_A2026.ZIP": write_cotahist(
                    tmp_path / "c2026.zip",
                    [
                        cotahist_line("20261118", "TEST3", 1412),
                        cotahist_line("20261119", "TEST3", 1430),
                    ],
                ),
                b3.supplement_url(LISTED, "TEST"): write_json(tmp_path / "supp.json", SUPPLEMENT),
                b3.cash_dividends_url(LISTED, "TESTE", 1): write_json(
                    tmp_path / "p1.json",
                    cash_page(
                        [cash_item("JRS CAP PROPRIO", "0,10245643978", "01/09/2026", "10/08/2026")],
                        total_pages=2,
                    ),
                ),
                b3.cash_dividends_url(LISTED, "TESTE", 2): write_json(
                    tmp_path / "p2.json",
                    cash_page(
                        [cash_item("DIVIDENDO", "0,5", "11/03/2025", "20/02/2025")],
                        page=2,
                        total_pages=2,
                    ),
                ),
                macro.brapi_quote_url(BRAPI, "TEST3"): write_json(
                    tmp_path / "quote.json",
                    {
                        "results": [
                            {
                                "symbol": "TEST3",
                                "currency": "BRL",
                                "regularMarketPrice": 14.3,
                                "regularMarketTime": "2026-11-20T21:30:00.000Z",
                            }
                        ]
                    },
                ),
            }
        )
        yield conn, fetcher


def _market(conn, fetcher, token="secret-token"):
    return sync_market(
        conn,
        "TEST3",
        cotahist_base_url=COTAHIST,
        listed_base_url=LISTED,
        brapi_base_url=BRAPI,
        brapi_token=token,
        fetcher=fetcher,
        years=1,
        today=TODAY,
    )


class TestMarketSync:
    def test_prices_events_and_quote_are_loaded(self, synced):
        conn, fetcher = synced
        report = _market(conn, fetcher)

        assert report.prices_added == 2
        assert report.last_trade_date == date(2026, 11, 19)
        assert report.events_added == 5  # 2 cash events + split + reverse split + bonus
        assert conn.execute("SELECT isin FROM securities").fetchone()[0] == "BRTESTACNOR1"
        jcp = conn.execute(
            "SELECT value_per_share, is_gross, payment_date FROM corporate_actions "
            "WHERE action_type = 'jcp'"
        ).fetchone()
        assert jcp == (Decimal("0.10245643978000"), True, date(2026, 9, 11))  # exact
        assert report.quote is not None and report.quote.price == Decimal("14.3")

    def test_token_goes_in_the_header_never_in_the_manifest(self, synced):
        conn, fetcher = synced
        _market(conn, fetcher)
        url = macro.brapi_quote_url(BRAPI, "TEST3")

        assert fetcher.headers[url] == {"Authorization": "Bearer secret-token"}
        urls = [row[0] for row in conn.execute("SELECT url FROM source_files").fetchall()]
        assert not any("secret-token" in u for u in urls)

    def test_second_run_adds_nothing(self, synced):
        conn, fetcher = synced
        _market(conn, fetcher)
        again = _market(conn, fetcher)

        assert (again.prices_added, again.events_added) == (0, 0)
        assert again.price_files_unchanged == ["COTAHIST_A2026.ZIP"]

    def test_missing_token_only_warns(self, synced):
        conn, fetcher = synced
        report = _market(conn, fetcher, token=None)
        assert report.quote is None
        assert any("BRAPI_TOKEN" in w for w in report.warnings)

    def test_requires_cvm_sync_first(self, tmp_path):
        db_path = tmp_path / "empty.duckdb"
        init_database(db_path)
        with connect(db_path) as conn, pytest.raises(TickerNotFoundError):
            _market(conn, None)


def test_macro_sync_is_idempotent(tmp_path):
    from tests.cvm_files import FakeFetcher

    db_path = tmp_path / "w.duckdb"
    init_database(db_path)
    fetcher = FakeFetcher()
    for start, end in macro.sgs_windows(date(2026, 1, 1), TODAY):
        for code in macro.SGS_SERIES:
            fetcher.files[macro.sgs_url(SGS, code, start, end)] = write_json(
                tmp_path / f"sgs{code}.json",
                [{"data": "01/10/2026", "valor": "0.14"}, {"data": "01/12/2026", "valor": "1"}],
            )
    with connect(db_path) as conn:
        first = sync_macro(conn, sgs_base_url=SGS, fetcher=fetcher, years=1, today=TODAY)
        second = sync_macro(conn, sgs_base_url=SGS, fetcher=fetcher, years=1, today=TODAY)
        assert (first.points_added, second.points_added) == (2, 0)
        assert first.last_points["bcb_sgs_433"] == (date(2026, 10, 1), "0.0014000000")
