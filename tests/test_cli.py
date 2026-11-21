from __future__ import annotations

from engine.cli import main
from engine.settings import get_settings


def test_init_db_creates_database_and_is_idempotent(capsys):
    assert main(["init-db"]) == 0
    assert "0001_initial" in capsys.readouterr().out
    assert get_settings().db_path.exists()

    assert main(["init-db"]) == 0
    assert "nenhuma migração pendente" in capsys.readouterr().out


def test_export_schemas_check_passes_on_committed_schemas(capsys):
    assert main(["export-schemas", "--check"]) == 0
    assert "em dia" in capsys.readouterr().out


def test_doctor_reports_missing_token_as_error(capsys):
    main(["init-db"])
    capsys.readouterr()
    assert main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "BRAPI_TOKEN vazio" in out
    assert "[ok   ] banco em" in out
