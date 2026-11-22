"""Command line interface: `skillsinvest <command>` (or `python -m engine <command>`).

Messages are in Portuguese because they are read by the investor.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from decimal import Decimal

from engine import __version__
from engine.config import DEFAULTS_PATH, load_config, load_sector_overrides
from engine.contract.export import SCHEMAS_DIR, export_schemas, outdated_schemas
from engine.db import connect, init_database, pending_migrations
from engine.db.reference import read_cvm_sector_map
from engine.indicators.core import compute_indicators
from engine.ingest.http import HttpFetcher, purge_expired_cache
from engine.ingest.market_sync import sync_macro, sync_market
from engine.ingest.sync import TickerNotFoundError, sync_company
from engine.report.render import render_report
from engine.settings import EXTERNAL_URL_FIELDS, PROJECT_ROOT, env_file_path, get_settings
from engine.snapshot.build import SnapshotError, build_snapshot, write_snapshot
from engine.snapshot.folder import AnalysisFolder, AnalysisStateError
from engine.validation.checks import run_validation
from engine.valuation.bazin import value_bazin
from engine.valuation.graham import value_graham


def _cmd_sync(args: argparse.Namespace) -> int:
    settings = get_settings()
    config = load_config()
    init_database(settings.db_path)
    purge_expired_cache(settings.cache_dir)
    print(f"sincronizando {args.ticker.upper()} a partir de {settings.cvm_base_url} ...")
    with connect(settings.db_path) as conn:
        try:
            report = sync_company(
                conn,
                args.ticker,
                cvm_base_url=settings.cvm_base_url,
                config=config.sync,
                fetcher=HttpFetcher(settings.cache_dir / "cvm"),
                sector_map=read_cvm_sector_map(),
                sector_overrides=load_sector_overrides(),
            )
        except TickerNotFoundError as exc:
            print(f"erro: {exc}")
            return 1
    print(f"empresa: {report.name} (CNPJ {report.cnpj})")
    print(f"template contábil: {report.accounting_template} | setor: {report.sector or '—'}")
    print(f"arquivos carregados: {', '.join(report.files_loaded) or 'nenhum'}")
    print(f"arquivos sem mudança: {', '.join(report.files_unchanged) or 'nenhum'}")
    print(f"documentos novos: {report.filings_added} | fatos novos: {report.facts_added}")
    for warning in report.warnings:
        print(f"aviso: {warning}")

    print(f"cotações e proventos da B3 ({settings.b3_cotahist_base_url}) ...")
    with connect(settings.db_path) as conn:
        market = sync_market(
            conn,
            args.ticker,
            cotahist_base_url=settings.b3_cotahist_base_url,
            listed_base_url=settings.b3_listed_base_url,
            brapi_base_url=settings.brapi_base_url,
            brapi_token=settings.require_brapi_token() if settings.has_brapi_token() else None,
            fetcher=HttpFetcher(settings.cache_dir / "b3"),
            years=config.sync.history_years,
        )
        print(f"tickers: {', '.join(market.tickers)}")
        print(f"arquivos COTAHIST carregados: {', '.join(market.price_files_loaded) or 'nenhum'}")
        print(
            f"arquivos COTAHIST sem mudança: {', '.join(market.price_files_unchanged) or 'nenhum'}"
        )
        print(f"pregões novos: {market.prices_added} | último pregão: {market.last_trade_date}")
        print(f"proventos e eventos novos: {market.events_added}")
        if market.quote:
            print(
                f"cotação brapi: {market.quote.ticker} R$ {_format_brl(market.quote.price)} "
                f"em {market.quote.quoted_at:%Y-%m-%d %H:%M} UTC"
            )
        for warning in market.warnings:
            print(f"aviso: {warning}")

        print(f"séries do Banco Central ({settings.bcb_sgs_base_url}) ...")
        macro_report = sync_macro(
            conn,
            sgs_base_url=settings.bcb_sgs_base_url,
            fetcher=HttpFetcher(settings.cache_dir / "bcb"),
            years=config.sync.history_years,
        )
        print(f"pontos novos: {macro_report.points_added}")
        for series_code, (ref_date, value) in macro_report.last_points.items():
            print(f"  {series_code}: {value} em {ref_date}")
    return 0


def _cmd_snapshot(args: argparse.Namespace) -> int:
    settings = get_settings()
    with connect(settings.db_path, read_only=True) as conn:
        try:
            data = build_snapshot(conn, args.ticker)
        except SnapshotError as exc:
            print(f"erro: {exc}")
            return 1
    path = write_snapshot(data, args.ticker)
    print(f"snapshot: {path.relative_to(PROJECT_ROOT)}")
    print(f"data-base: {data.reference_date} | tirado em: {data.as_of}")
    for ticker, price in data.market.prices.items():
        print(f"preço {ticker}: R$ {_format_brl(price.value)} em {price.period.end}")
    print(
        f"conceitos: {len(data.financials)} | valores: "
        f"{sum(len(v) for v in data.financials.values())} | proventos e eventos: "
        f"{len(data.corporate_actions)} | fontes: {len(data.sources)}"
    )
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    try:
        folder = AnalysisFolder.latest(args.ticker)
    except AnalysisStateError as exc:
        print(f"erro: {exc}")
        return 1
    with connect(get_settings().db_path, read_only=True) as conn:
        report = run_validation(folder.data, conn, args.ticker)
    path = folder.write("validation.json", report)
    labels = {"info": "info", "warning": "aviso", "error": "erro"}
    for check in report.checks:
        status = "ok" if check.passed else labels[check.severity]
        print(f"[{status:5}] {check.id}: {check.message}")
        if not check.passed or args.verbose:
            for detail in check.details:
                print(f"          - {detail}")
    print(f"validação: {path.relative_to(PROJECT_ROOT)}")
    if report.blocking:
        print("BLOQUEADO: corrija os erros antes de rodar qualquer valuation.")
        return 1
    return 0


def _cmd_indicators(args: argparse.Namespace) -> int:
    try:
        folder = AnalysisFolder.latest(args.ticker)
        folder.validation()
    except AnalysisStateError as exc:
        print(f"erro: {exc}")
        return 1
    report = compute_indicators(folder.data, args.ticker, load_config().bazin)
    path = folder.write("indicators.json", report)
    for name, value in report.values.items():
        print(f"{name:34} {_format_value(value.value, value.unit)}")
    for name, reason in report.unavailable.items():
        print(f"{name:34} indisponível: {reason}")
    print(f"indicadores: {path.relative_to(PROJECT_ROOT)}")
    return 0


def _cmd_valuate(args: argparse.Namespace) -> int:
    try:
        folder = AnalysisFolder.latest(args.ticker)
        folder.validation()
        indicators = folder.indicators()
    except AnalysisStateError as exc:
        print(f"erro: {exc}")
        return 1
    config = load_config()
    results = []
    if args.method in ("graham", "all"):
        results.append(value_graham(folder.data, indicators, args.ticker, config))
    if args.method in ("bazin", "all"):
        for net in (False, True):
            results.append(value_bazin(folder.data, indicators, args.ticker, config, net=net))
    for result in results:
        path = folder.write(f"valuations/{result.method}.json", result)
        print(f"{result.method}: {path.relative_to(PROJECT_ROOT)}")
        if not result.applicable:
            print(f"  não aplicável: {result.not_applicable_reason}")
            continue
        out = result.result
        if out.fair_value is not None:
            print(f"  valor justo: R$ {_format_brl(out.fair_value)}")
        if out.ceiling_price is not None:
            print(f"  preço-teto: R$ {_format_brl(out.ceiling_price)}")
        for ceiling in out.ceiling_prices:
            print(
                f"  preço-teto com margem de {ceiling.margin_of_safety * 100:.0f}%: "
                f"R$ {_format_brl(ceiling.price)}"
            )
        if out.price is not None:
            print(f"  preço atual: R$ {_format_brl(out.price)}")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    try:
        folder = AnalysisFolder.latest(args.ticker)
        path = render_report(folder, args.ticker)
    except AnalysisStateError as exc:
        print(f"erro: {exc}")
        return 1
    print(f"relatório: {path.relative_to(PROJECT_ROOT)}")
    return 0


def _format_value(value: Decimal, unit: str) -> str:
    if unit == "ratio":
        return f"{value:.4f}"
    if unit == "shares":
        return f"{value:,.0f}".replace(",", ".")
    return f"R$ {_format_brl(value)}" + (" por ação" if unit == "BRL/share" else "")


def _format_brl(value: Decimal) -> str:
    text = f"{value:,.2f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def _cmd_series(args: argparse.Namespace) -> int:
    settings = get_settings()
    with connect(settings.db_path, read_only=True) as conn:
        rows = conn.execute(
            """
            SELECT f.period_type, f.period_start, f.period_end, f.value, f.unit,
                   f.doc_type, f.reference_date, f.version
            FROM v_concept_facts AS f
            JOIN securities AS s ON s.cnpj = f.cnpj
            WHERE s.ticker = ? AND f.concept = ? AND f.basis = ?
              AND (? IS NULL OR f.period_type = ?)
            ORDER BY f.period_end, f.period_type
            """,
            [args.ticker.upper(), args.concept, args.basis, args.period, args.period],
        ).fetchall()
    if not rows:
        print(f"nenhum valor de {args.concept} para {args.ticker.upper()} — rode o sync antes")
        return 1
    print(f"{args.ticker.upper()} · {args.concept} · {args.basis}")
    for period_type, start, end, value, unit, doc_type, ref, version in rows:
        period = f"{start} a {end}" if start else f"em {end}"
        print(
            f"{period_type:7} {period:26} {_format_brl(value):>24} {unit:9} "
            f"({doc_type} {ref} v{version})"
        )
    return 0


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

    for name in EXTERNAL_URL_FIELDS:
        report("ok", f"{name.upper()} = {getattr(settings, name)}")

    return 1 if errors else 0


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "init-db": _cmd_init_db,
    "export-schemas": _cmd_export_schemas,
    "doctor": _cmd_doctor,
    "sync": _cmd_sync,
    "series": _cmd_series,
    "snapshot": _cmd_snapshot,
    "validate": _cmd_validate,
    "indicators": _cmd_indicators,
    "valuate": _cmd_valuate,
    "report": _cmd_report,
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
    sub.add_parser("doctor", help="verifica .env, tokens, configuração, schemas, banco e URLs")
    sync = sub.add_parser(
        "sync", help="carrega no banco os dados da CVM, B3, brapi e Banco Central de uma empresa"
    )
    sync.add_argument("ticker", help="código de negociação, ex.: BBAS3")
    series = sub.add_parser("series", help="mostra a série histórica de um conceito no banco")
    series.add_argument("ticker", help="código de negociação, ex.: BBAS3")
    series.add_argument("concept", help="conceito do account_map, ex.: net_income")
    series.add_argument("--period", choices=["INSTANT", "3M", "YTD", "FY"], default=None)
    series.add_argument("--basis", choices=["consolidated", "individual"], default="consolidated")
    snapshot = sub.add_parser(
        "snapshot", help="gera analyses/<TICKER>/<data-base>/data.json a partir do banco"
    )
    snapshot.add_argument("ticker", help="código de negociação, ex.: BBAS3")
    validate = sub.add_parser(
        "validate", help="valida o último data.json do ticker e grava validation.json"
    )
    validate.add_argument("ticker", help="código de negociação, ex.: BBAS3")
    validate.add_argument("-v", "--verbose", action="store_true", help="mostra todos os detalhes")
    indicators = sub.add_parser(
        "indicators", help="calcula os indicadores do último snapshot validado (indicators.json)"
    )
    indicators.add_argument("ticker", help="código de negociação, ex.: BBAS3")
    valuate = sub.add_parser(
        "valuate", help="roda os métodos de valuation e grava valuations/<método>.json"
    )
    valuate.add_argument("ticker", help="código de negociação, ex.: BBAS3")
    valuate.add_argument("--method", choices=["graham", "bazin", "all"], default="all")
    report = sub.add_parser("report", help="gera o relatório HTML da última análise (report.html)")
    report.add_argument("ticker", help="código de negociação, ex.: BBAS3")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)
