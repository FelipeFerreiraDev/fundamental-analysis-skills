from __future__ import annotations

from datetime import datetime
from decimal import Decimal

import pytest

from engine.config import load_config
from engine.contract.validation import ValidationReport
from engine.indicators.core import compute_indicators
from engine.report import formatting as fmt
from engine.report.charts import column_chart, nice_ticks
from engine.report.render import render_report
from engine.snapshot.folder import AnalysisFolder, AnalysisStateError
from engine.valuation.bazin import value_bazin
from engine.valuation.graham import value_graham
from tests.test_valuation import AS_OF, _data

CONFIG = load_config()


class TestFormatting:
    def test_brazilian_formats(self):
        assert fmt.brl(Decimal("1234.567")) == "R$ 1.234,57"
        assert fmt.brl(Decimal("-2")) == "−R$ 2,00"
        assert fmt.brl_compact(Decimal("11016424000")) == "R$ 11,02 bi"
        assert fmt.brl_compact(Decimal("2500000")) == "R$ 2,50 mi"
        assert fmt.percent(Decimal("0.0483")) == "4,83%"
        assert fmt.multiple(Decimal("7.4107")) == "7,41x"
        assert fmt.number(Decimal("5709020778"), 0) == "5.709.020.778"
        assert fmt.brl(None) == "—"


class TestCharts:
    def test_nice_ticks_include_zero_and_cover_range(self):
        assert nice_ticks(7.0, 29.9) == [0, 10, 20, 30]
        ticks = nice_ticks(-3.0, 12.0)
        assert ticks[0] <= -3 and ticks[-1] >= 12 and 0 in ticks

    def test_column_chart_is_escaped_svg_with_tooltips(self):
        svg = column_chart(
            "Teste <x>",
            [("2024", Decimal("2")), ("2025", Decimal("-1"))],
            axis_format=fmt.brl,
            value_format=fmt.brl,
        )
        assert svg.startswith("<svg") and "Teste &lt;x&gt;" in svg
        assert svg.count('class="bar"') == 2
        assert "<title>2025: −R$ 1,00</title>" in svg
        assert column_chart("vazio", [], axis_format=str, value_format=str) == ""


@pytest.fixture
def folder(tmp_path):
    data = _data()
    path = tmp_path / "TEST3" / "2026-09-30"
    folder = AnalysisFolder(path=path, data=data)
    path.mkdir(parents=True)
    (path / "data.json").write_text(data.model_dump_json(), encoding="utf-8")
    folder.write(
        "validation.json",
        ValidationReport(
            ticker="TEST3",
            reference_date=data.reference_date,
            snapshot_as_of=data.as_of,
            generated_at=AS_OF,
            engine_version="test",
            checks=[
                {"id": "required_inputs", "severity": "error", "passed": True, "message": "ok"},
                {
                    "id": "large_price_moves",
                    "severity": "warning",
                    "passed": False,
                    "message": "Queda forte <sem evento>",
                    "details": ["TEST3 2026-10-26: −29%"],
                },
            ],
            blocking=False,
        ),
    )
    indicators = compute_indicators(data, "TEST3", CONFIG.bazin, now=AS_OF)
    folder.write("indicators.json", indicators)
    return folder, data, indicators


def test_report_renders_every_section_from_the_files(folder):
    folder, data, indicators = folder
    graham = value_graham(data, indicators, "TEST3", CONFIG, now=AS_OF)
    folder.write("valuations/graham_number.json", graham)
    folder.write(
        "valuations/bazin_gross.json",
        value_bazin(data, indicators, "TEST3", CONFIG, net=False, now=AS_OF),
    )
    html = render_report(folder, "test3", now=datetime(2026, 11, 21, 16)).read_text("utf-8")

    for anchor in ("resumo", "avisos", "indicadores", "historico", "metodos", "fontes"):
        assert f'id="{anchor}"' in html
    assert fmt.brl(graham.result.fair_value) in html
    assert "Queda forte &lt;sem evento&gt;" in html  # escaped
    assert "não constitui recomendação de investimento" in html
    assert 'id="src-test-dfp-2025"' in html
    assert "None" not in html
    assert "<svg" in html


def test_report_requires_valuations(folder):
    folder, _, _ = folder
    with pytest.raises(AnalysisStateError, match="valuate"):
        render_report(folder, "TEST3")
