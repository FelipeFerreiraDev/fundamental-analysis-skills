from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from engine.config import SyncConfig
from engine.db import connect, init_database
from engine.db.reference import read_cvm_sector_map
from engine.ingest import cvm
from engine.ingest.sync import TickerNotFoundError, sync_company
from tests.cvm_files import (
    BALANCE_HEADER,
    BANK,
    CAD_HEADER,
    CAPITAL_HEADER,
    FCA_HEADER,
    MAIN_HEADER,
    OTHER,
    STATEMENT_HEADER,
    FakeFetcher,
    balance,
    capital,
    dre,
    main_row,
    write_csv,
    write_zip,
)

BASE = "https://cvm.test"
TODAY = date(2026, 11, 21)


def _itr_2026(tmp_path, *, version=1, net_income="2000.5"):
    return write_zip(
        tmp_path / f"itr2026_v{version}.zip",
        {
            "itr_cia_aberta_2026.csv": [
                MAIN_HEADER,
                main_row(BANK, "2026-06-30", version, "ITR", 9, "2026-08-12"),
                main_row(OTHER, "2026-06-30", 1, "ITR", 10, "2026-08-10"),
            ],
            "itr_cia_aberta_DRE_con_2026.csv": [
                STATEMENT_HEADER,
                dre(
                    BANK,
                    "2026-06-30",
                    version,
                    "2026-04-01",
                    "2026-06-30",
                    "3.01",
                    "Receitas de Intermediação Financeira",
                    "1000",
                ),
                dre(
                    BANK,
                    "2026-06-30",
                    version,
                    "2026-01-01",
                    "2026-06-30",
                    "3.11.01",
                    "Atribuído aos Sócios da Empresa Controladora",
                    net_income,
                ),
                dre(
                    BANK,
                    "2026-06-30",
                    version,
                    "2026-01-01",
                    "2026-06-30",
                    "3.99.01.01",
                    "ON",
                    "1.23",
                ),
                dre(OTHER, "2026-06-30", 1, "2026-01-01", "2026-06-30", "3.11.01", "Outra", "7"),
            ],
            "itr_cia_aberta_BPP_con_2026.csv": [
                BALANCE_HEADER,
                balance(
                    BANK,
                    "2026-06-30",
                    version,
                    "2026-06-30",
                    "2.07.01",
                    "Patrimônio Líquido Atribuído ao Controlador",
                    "50000",
                ),
            ],
            "itr_cia_aberta_composicao_capital_2026.csv": [
                CAPITAL_HEADER,
                capital(BANK, "2026-06-30", version, 1000, 0, 10, 0),
            ],
        },
    )


def _dfp(tmp_path, year, *, layout="new", net_income="900"):
    ref = f"{year}-12-31"
    code, name = (
        ("3.11.01", "Atribuído aos Sócios da Empresa Controladora")
        if layout == "new"
        else ("3.09.01", "Atribuído a Sócios da Empresa Controladora")
    )
    return write_zip(
        tmp_path / f"dfp{year}.zip",
        {
            f"dfp_cia_aberta_{year}.csv": [
                MAIN_HEADER,
                main_row(BANK, ref, 1, "DFP", year, f"{year + 1}-02-15"),
            ],
            f"dfp_cia_aberta_DRE_con_{year}.csv": [
                STATEMENT_HEADER,
                dre(
                    BANK,
                    ref,
                    1,
                    f"{year}-01-01",
                    ref,
                    "3.01",
                    "Receitas da Intermediação Financeira",
                    "1",
                ),
                dre(BANK, ref, 1, f"{year}-01-01", ref, code, name, net_income),
            ],
        },
    )


def _fetcher(tmp_path, **extra) -> FakeFetcher:
    cad = write_csv(
        tmp_path / "cad.csv",
        [
            CAD_HEADER,
            f"{BANK};BANCO TESTE S.A.;BANCO TESTE;1977-07-20;1905-12-30;;;ATIVO;1977-07-20;1023;"
            "Bancos;BOLSA;Categoria A;2010-01-01;FASE OPERACIONAL;1977-07-20;ESTATAL",
        ],
    )
    fca = write_zip(
        tmp_path / "fca2026.zip",
        {
            "fca_cia_aberta_valor_mobiliario_2026.csv": [
                FCA_HEADER,
                f"{BANK};2026-01-01;3;1;BANCO TESTE;Ações Ordinárias;;;TEST3;;Bolsa;B3;B3;"
                "2006-05-31;;Novo Mercado;1977-07-20;",
                f"{BANK};2026-01-01;3;1;BANCO TESTE;Debêntures;;;TEST11;;Bolsa;B3;B3;"
                "2020-01-01;;;;",
                f"{OTHER};2026-01-01;1;2;OUTRA;Ações Preferenciais;PNA;Classe A;OTHR5;;Bolsa;B3;B3;"
                "2001-01-01;;;;",
            ]
        },
    )
    files = {
        f"{BASE}/CAD/DADOS/cad_cia_aberta.csv": cad,
        f"{BASE}/DOC/FCA/DADOS/fca_cia_aberta_2026.zip": fca,
        f"{BASE}/DOC/ITR/DADOS/itr_cia_aberta_2026.zip": _itr_2026(tmp_path),
        f"{BASE}/DOC/DFP/DADOS/dfp_cia_aberta_2019.zip": _dfp(tmp_path, 2019, layout="old"),
        f"{BASE}/DOC/DFP/DADOS/dfp_cia_aberta_2025.zip": _dfp(tmp_path, 2025),
    }
    files.update(extra)
    return FakeFetcher(files=files)


def _sync(conn, fetcher, ticker="TEST3"):
    return sync_company(
        conn,
        ticker,
        cvm_base_url=BASE,
        config=SyncConfig(history_years=8, quarterly_years=1),
        fetcher=fetcher,
        sector_map=read_cvm_sector_map(),
        sector_overrides={},
        today=TODAY,
    )


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "w.duckdb"
    init_database(db_path)
    with connect(db_path) as connection:
        yield connection


class TestParsing:
    def test_scale_period_types_and_company_filter(self, tmp_path):
        docs = cvm.parse_documents(_itr_2026(tmp_path), "ITR", BANK)
        facts = {f.account_code: f for f in docs.facts}

        assert [f.reference_date for f in docs.filings] == [date(2026, 6, 30)]
        assert facts["3.01"].value == Decimal("1000000")  # MIL -> unit
        assert facts["3.01"].period_type == "3M"
        assert facts["3.11.01"].value == Decimal("2000500.0")
        assert facts["3.11.01"].period_type == "YTD"
        assert facts["3.99.01.01"].value == Decimal("1.23")  # per share: never scaled
        assert facts["3.99.01.01"].unit == "BRL/share"
        assert facts["2.07.01"].period_type == "INSTANT"
        assert facts["2.07.01"].period_start is None
        assert docs.shares[0].total == 1000 and docs.shares[0].treasury == 10
        assert all(f.account_name != "Outra" for f in docs.facts)

    def test_first_quarter_is_year_to_date(self):
        assert cvm.classify_period("ITR", "DRE", date(2026, 1, 1), date(2026, 3, 31)) == (
            "YTD",
            date(2026, 1, 1),
        )
        assert cvm.classify_period("DFP", "DRE", date(2025, 1, 1), date(2025, 12, 31))[0] == "FY"

    def test_unsupported_currency_is_rejected(self, tmp_path):
        path = write_zip(
            tmp_path / "bad.zip",
            {
                "itr_cia_aberta_2026.csv": [
                    MAIN_HEADER,
                    main_row(BANK, "2026-06-30", 1, "ITR", 1, "2026-08-01"),
                ],
                "itr_cia_aberta_DRE_con_2026.csv": [
                    STATEMENT_HEADER,
                    dre(
                        BANK,
                        "2026-06-30",
                        1,
                        "2026-01-01",
                        "2026-06-30",
                        "3.01",
                        "X",
                        "1",
                        currency="DOLAR",
                    ),
                ],
            },
        )
        with pytest.raises(cvm.CvmFormatError, match="currency"):
            cvm.parse_documents(path, "ITR", BANK)

    def test_rows_without_filing_are_rejected(self, tmp_path):
        path = write_zip(
            tmp_path / "orphan.zip",
            {
                "itr_cia_aberta_2026.csv": [MAIN_HEADER],
                "itr_cia_aberta_DRE_con_2026.csv": [
                    STATEMENT_HEADER,
                    dre(BANK, "2026-06-30", 1, "2026-01-01", "2026-06-30", "3.01", "X", "1"),
                ],
            },
        )
        with pytest.raises(cvm.CvmFormatError, match="without a filing"):
            cvm.parse_documents(path, "ITR", BANK)

    def test_template_detection(self, tmp_path):
        bank = cvm.parse_documents(_itr_2026(tmp_path), "ITR", BANK).facts
        assert cvm.detect_accounting_template(bank) == "bank"
        assert cvm.detect_accounting_template([]) is None

    def test_sector_profile_ignores_holding_prefix(self):
        sectors = read_cvm_sector_map()
        assert cvm.sector_profile("Bancos", sectors) == "banking"
        assert cvm.sector_profile("Emp. Adm. Part. - Energia Elétrica", sectors) == "utilities"
        assert cvm.sector_profile("Securitização de Recebíveis", sectors) is None


class TestSync:
    def test_loads_company_documents_and_concepts(self, conn, tmp_path):
        report = _sync(conn, _fetcher(tmp_path))

        assert (report.cnpj, report.accounting_template, report.sector) == (
            "00000000000191",
            "bank",
            "banking",
        )
        assert report.filings_added == 3
        company = conn.execute("SELECT name, control_type, cvm_sector FROM companies").fetchone()
        assert company == ("BANCO TESTE S.A.", "ESTATAL", "Bancos")
        assert conn.execute("SELECT ticker, share_class FROM securities").fetchall() == [
            ("TEST3", "ON")
        ]
        net_income = conn.execute(
            "SELECT period_type, period_end, value FROM v_concept_facts "
            "WHERE concept = 'net_income' ORDER BY period_end"
        ).fetchall()
        assert net_income == [
            ("FY", date(2019, 12, 31), Decimal("900000.0000")),  # old layout: 3.09.01
            ("FY", date(2025, 12, 31), Decimal("900000.0000")),  # new layout: 3.11.01
            ("YTD", date(2026, 6, 30), Decimal("2000500.0000")),
        ]
        assert conn.execute("SELECT count(*) FROM financial_facts").fetchone()[0] == 8

    def test_second_run_skips_unchanged_files(self, conn, tmp_path):
        fetcher = _fetcher(tmp_path)
        _sync(conn, fetcher)
        downloads = len(fetcher.downloads)
        report = _sync(conn, fetcher)

        assert report.filings_added == 0
        assert report.files_loaded == []
        assert len(report.files_unchanged) == 3
        # only the registry and the FCA (needed to resolve the ticker) are fetched again
        assert len(fetcher.downloads) == downloads + 2

    def test_restatement_adds_a_version_and_wins(self, conn, tmp_path):
        fetcher = _fetcher(tmp_path)
        _sync(conn, fetcher)
        url = f"{BASE}/DOC/ITR/DADOS/itr_cia_aberta_2026.zip"
        fetcher.files[url] = _itr_2026(tmp_path, version=2, net_income="1800")
        fetcher.etags[url] = "v2"
        report = _sync(conn, fetcher)

        assert report.filings_added == 1
        values = conn.execute(
            "SELECT f.version, ff.value FROM financial_facts ff "
            "JOIN filings f ON f.id = ff.filing_id "
            "WHERE ff.account_code = '3.11.01' AND f.doc_type = 'ITR' ORDER BY f.version"
        ).fetchall()
        assert values == [(1, Decimal("2000500.0000")), (2, Decimal("1800000.0000"))]
        latest = conn.execute(
            "SELECT value FROM v_concept_facts WHERE concept = 'net_income' AND period_type = 'YTD'"
        ).fetchone()[0]
        assert latest == Decimal("1800000.0000")

    def test_unknown_ticker(self, conn, tmp_path):
        with pytest.raises(TickerNotFoundError, match="XXXX3"):
            _sync(conn, _fetcher(tmp_path), ticker="XXXX3")

    def test_manifest_records_scope_and_runs(self, conn, tmp_path):
        _sync(conn, _fetcher(tmp_path))
        datasets = conn.execute(
            "SELECT dataset, status FROM ingestion_runs ORDER BY dataset"
        ).fetchall()
        assert datasets == [
            ("cad", "success"),
            ("dfp", "success"),
            ("fca", "success"),
            ("itr", "success"),
        ]
        scopes = conn.execute("SELECT DISTINCT cnpj FROM source_file_scopes").fetchall()
        assert scopes == [("00000000000191",)]
