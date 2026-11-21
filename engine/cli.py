"""Command line interface: `skillsinvest <command>` (or `python -m engine <command>`).

Messages are in Portuguese because they are read by the investor.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence

from engine import __version__
from engine.config import DEFAULTS_PATH, load_config
from engine.contract.export import SCHEMAS_DIR, export_schemas, outdated_schemas
from engine.db import connect, init_database, pending_migrations
from engine.settings import PROJECT_ROOT, env_file_path, get_settings


def _cmd_init_db(_: argparse.Namespace) -> int:
    settings = get_settings()
    applied = init_database(settings.db_path)
    if applied:
        for migration in applied:
            print(f"migração aplicada: {migration.version:04d}_{migration.name}")
    else:
        print("nenhuma migração pendente")
    print(f"banco: {settings.db_path}")
    return 0


def _cmd_export_schemas(args: argparse.Namespace) -> int:
    if args.check:
        outdated = outdated_schemas(SCHEMAS_DIR)
        if outdated:
            print("schemas desatualizados: " + ", ".join(outdated))
            print("rode: skillsinvest export-schemas")
            return 1
        print("schemas em dia")
        return 0
    for path in export_schemas(SCHEMAS_DIR):
        print(f"gerado: {path.relative_to(PROJECT_ROOT)}")
    return 0


def _cmd_doctor(_: argparse.Namespace) -> int:
    settings = get_settings()
    errors = 0

    def report(level: str, message: str) -> None:
        nonlocal errors
        errors += level == "erro"
        print(f"[{level:5}] {message}")

    if env_file_path().exists():
        report("ok", ".env encontrado")
    else:
        report("erro", ".env não encontrado — copie .env.example para .env")

    if settings.has_brapi_token():
        report("ok", "BRAPI_TOKEN configurado")
    else:
        report("erro", "BRAPI_TOKEN vazio — necessário para a cotação do dia")

    config_name = DEFAULTS_PATH.relative_to(PROJECT_ROOT)
    try:
        load_config()
        report("ok", f"{config_name} válido")
    except Exception as exc:  # any parsing or validation error is shown to the user
        report("erro", f"{config_name} inválido: {exc}")

    outdated = outdated_schemas(SCHEMAS_DIR)
    if outdated:
        names = ", ".join(outdated)
        report("erro", f"schemas desatualizados ({names}) — rode: skillsinvest export-schemas")
    else:
        report("ok", "schemas do contrato em dia")

    if not settings.db_path.exists():
        report("aviso", "banco ainda não criado — rode: skillsinvest init-db")
    else:
        with connect(settings.db_path, read_only=True) as conn:
            pending = pending_migrations(conn)
        if pending:
            report("erro", f"{len(pending)} migração(ões) pendente(s) — rode: skillsinvest init-db")
        else:
            report("ok", f"banco em {settings.db_path}")

    return 1 if errors else 0


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "init-db": _cmd_init_db,
    "export-schemas": _cmd_export_schemas,
    "doctor": _cmd_doctor,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skillsinvest",
        description="Engine do skillsInvest — análise fundamentalista auditável de empresas da B3.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db", help="cria o banco local e aplica as migrações pendentes")
    export = sub.add_parser("export-schemas", help="gera os JSON Schemas do contrato em schemas/")
    export.add_argument("--check", action="store_true", help="só verifica se estão em dia")
    sub.add_parser("doctor", help="verifica .env, tokens, configuração, schemas e banco")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)
