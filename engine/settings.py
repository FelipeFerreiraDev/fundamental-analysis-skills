"""Runtime settings read from environment variables and the project's `.env` file.

Credentials live only in `.env` (never in code or `config/`). Every variable read here
must also be listed, without a value, in `.env.example`.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"


def env_file_path() -> Path:
    """Location of `.env`. SKILLSINVEST_ENV_FILE overrides it (the test suite uses this)."""
    return Path(os.environ.get("SKILLSINVEST_ENV_FILE", DEFAULT_ENV_FILE))


class MissingSettingError(RuntimeError):
    """Raised when a setting required by the current operation is not configured."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    brapi_token: SecretStr | None = None
    data_dir: Path = PROJECT_ROOT / "data"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "warehouse.duckdb"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def documents_dir(self) -> Path:
        return self.data_dir / "documents"

    def has_brapi_token(self) -> bool:
        return self.brapi_token is not None and bool(self.brapi_token.get_secret_value().strip())

    def require_brapi_token(self) -> str:
        if not self.has_brapi_token():
            raise MissingSettingError(
                "BRAPI_TOKEN não configurado. Copie .env.example para .env e preencha o token."
            )
        assert self.brapi_token is not None
        return self.brapi_token.get_secret_value().strip()


@lru_cache
def get_settings() -> Settings:
    return Settings(_env_file=env_file_path())
