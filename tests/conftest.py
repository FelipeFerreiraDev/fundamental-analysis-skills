from __future__ import annotations

import json
from pathlib import Path

import pytest

from engine.settings import get_settings

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def bbas3_company() -> dict:
    return json.loads((FIXTURES / "bbas3" / "company.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch, tmp_path):
    """Keep tests away from the real .env (and its tokens) and the real data/ directory."""
    monkeypatch.setenv("SKILLSINVEST_ENV_FILE", str(tmp_path / "test.env"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("BRAPI_TOKEN", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
