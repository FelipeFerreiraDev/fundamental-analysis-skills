from __future__ import annotations

from decimal import Decimal

import pytest

from engine.config import load_config
from engine.settings import MissingSettingError, Settings


def test_missing_token_raises_clear_error(tmp_path):
    settings = Settings(_env_file=tmp_path / "missing.env")
    with pytest.raises(MissingSettingError, match="BRAPI_TOKEN"):
        settings.require_brapi_token()


def test_empty_token_counts_as_missing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BRAPI_TOKEN=\n", encoding="utf-8")
    assert not Settings(_env_file=env_file).has_brapi_token()


def test_token_is_read_from_env_file_and_hidden_in_repr(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("BRAPI_TOKEN=abc123\n", encoding="utf-8")
    settings = Settings(_env_file=env_file)
    assert settings.require_brapi_token() == "abc123"
    assert "abc123" not in repr(settings)


def test_data_dir_can_be_overridden(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "elsewhere"))
    settings = Settings(_env_file=None)
    assert settings.db_path == tmp_path / "elsewhere" / "warehouse.duckdb"


def test_defaults_file_loads_with_exact_decimals():
    config = load_config()
    assert config.bazin.target_dividend_yield == Decimal("0.06")
    assert config.valuation.margin_of_safety is None


def test_env_example_urls_match_settings_defaults():
    """The URLs in .env.example are the documented defaults; they must not drift."""
    from engine.settings import PROJECT_ROOT

    example = {}
    for line in (PROJECT_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            example[key.strip()] = value.strip()
    defaults = Settings(_env_file=None)
    for field in ("cvm_base_url", "b3_cotahist_base_url", "brapi_base_url", "bcb_sgs_base_url"):
        assert example[field.upper()] == getattr(defaults, field)


def test_urls_can_be_overridden_and_must_be_https(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("CVM_BASE_URL=https://mirror.example.com/cvm/\n", encoding="utf-8")
    assert Settings(_env_file=env_file).cvm_base_url == "https://mirror.example.com/cvm"
    env_file.write_text("CVM_BASE_URL=http://insecure.example.com\n", encoding="utf-8")
    with pytest.raises(ValueError, match="https"):
        Settings(_env_file=env_file)


def test_sector_overrides_file_loads():
    from engine.config import load_sector_overrides

    assert load_sector_overrides() == {}
