"""Parsing CVM open data (cadastro, FCA, DFP, ITR) for one company.

Files cover the whole market; only rows of the requested CNPJ are decoded. Normalization
rules applied here (docs/architecture.md §7.2):

* ESCALA_MOEDA is applied (MIL -> x1000), except for per-share accounts (DRE 3.99.*), which
  the CVM publishes in R$/share regardless of the statement scale.
* Balance sheet items are INSTANT. DFP flows are FY. ITR flows starting on January 1st are
  YTD (so the first quarter is stored as YTD) and the others are 3M.
* Each filing keeps its version; restatements become new rows, never updates.
"""

from __future__ import annotations

import csv
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import BinaryIO
from zipfile import ZipFile

ENCODING = "latin-1"
SCALES = {"MIL": Decimal(1000), "UNIDADE": Decimal(1)}
BALANCE_SHEETS = {"BPA", "BPP"}
EQUITY_SHARE_CLASSES = {"Ações Ordinárias": "ON", "Ações Preferenciais": "PN", "Units": "UNIT"}

_MAIN_FILE = re.compile(r"^(?:dfp|itr)_cia_aberta_\d{4}\.csv$")
_CAPITAL_FILE = re.compile(r"^(?:dfp|itr)_cia_aberta_composicao_capital_\d{4}\.csv$")
_STATEMENT_FILE = re.compile(
    r"^(?:dfp|itr)_cia_aberta_(BPA|BPP|DRE|DRA|DFC_MD|DFC_MI|DMPL|DVA)_(con|ind)_\d{4}\.csv$"
)
_SECURITIES_FILE = re.compile(r"^fca_cia_aberta_valor_mobiliario_\d{4}\.csv$")
_HOLDING_PREFIX = "Emp. Adm. Part. - "


class CvmFormatError(ValueError):
    """The file does not follow the layout this parser was written for."""


def cnpj_digits(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if len(digits) != 14:
        raise CvmFormatError(f"invalid CNPJ: {value!r}")
    return digits


def format_cnpj(digits: str) -> str:
    d = cnpj_digits(digits)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _split(raw: bytes) -> list[str]:
    return next(csv.reader([raw.decode(ENCODING).rstrip("\r\n")], delimiter=";"))


def read_rows(fh: BinaryIO, *, prefix: bytes | None = None) -> list[dict[str, str]]:
    """Rows of a CVM CSV, optionally only those whose line starts with `prefix`."""
    header = _split(fh.readline())
    rows = []
    for raw in fh:
        if prefix is not None and not raw.startswith(prefix):
            continue
        values = _split(raw)
        if len(values) != len(header):
            raise CvmFormatError(f"expected {len(header)} columns, got {len(values)}")
        rows.append(dict(zip(header, values, strict=True)))
    return rows


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _optional_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


# Registry (cadastro) -----------------------------------------------------------------


@dataclass(frozen=True)
class CompanyRegistry:
    cnpj: str
    cvm_code: int
    name: str
    cvm_sector: str | None
    control_type: str | None
    registration_status: str | None


def parse_registry(path: Path, cnpj: str) -> CompanyRegistry | None:
    prefix = f"{format_cnpj(cnpj)};".encode(ENCODING)
    with path.open("rb") as fh:
        rows = read_rows(fh, prefix=prefix)
    active = [row for row in rows if row.get("SIT") == "ATIVO"] or rows
    if not active:
        return None
    row = active[0]
    return CompanyRegistry(
        cnpj=cnpj_digits(row["CNPJ_CIA"]),
        cvm_code=int(row["CD_CVM"]),
        name=row["DENOM_SOCIAL"],
        cvm_sector=row.get("SETOR_ATIV") or None,
        control_type=row.get("CONTROLE_ACIONARIO") or None,
        registration_status=row.get("SIT") or None,
    )


def sector_profile(cvm_sector: str | None, sector_map: dict[str, str]) -> str | None:
    if not cvm_sector:
        return None
    return sector_map.get(cvm_sector.removeprefix(_HOLDING_PREFIX))


# Securities (FCA) ----------------------------------------------------------------------


@dataclass(frozen=True)
class ListedSecurity:
    ticker: str
    cnpj: str
    share_class: str
    valid_from: date


def parse_securities(zip_path: Path) -> list[ListedSecurity]:
    """Equity securities currently traded on the exchange, latest FCA version per ticker."""
    with ZipFile(zip_path) as zf:
        members = [name for name in zf.namelist() if _SECURITIES_FILE.match(name)]
        if not members:
            raise CvmFormatError(f"{zip_path.name} has no valor_mobiliario file")
        with zf.open(members[0]) as fh:
            rows = read_rows(fh)

    latest: dict[str, tuple[tuple[str, int], ListedSecurity]] = {}
    for row in rows:
        ticker = row.get("Codigo_Negociacao", "").strip().upper()
        kind = EQUITY_SHARE_CLASSES.get(row.get("Valor_Mobiliario", ""))
        if not ticker or kind is None or row.get("Mercado") != "Bolsa":
            continue
        if row.get("Data_Fim_Negociacao"):
            continue
        preferred = row.get("Sigla_Classe_Acao_Preferencial", "").strip().upper()
        share_class = preferred if kind == "PN" and preferred in {"PNA", "PNB"} else kind
        security = ListedSecurity(
            ticker=ticker,
            cnpj=cnpj_digits(row["CNPJ_Companhia"]),
            share_class=share_class,
            valid_from=_date(row.get("Data_Inicio_Negociacao") or row["Data_Referencia"]),
        )
        rank = (row["Data_Referencia"], int(row.get("Versao") or 0))
        if ticker not in latest or rank > latest[ticker][0]:
            latest[ticker] = (rank, security)
    return [security for _, security in latest.values()]


# Financial statements (DFP / ITR) -----------------------------------------------------


@dataclass(frozen=True)
class Filing:
    doc_type: str
    reference_date: date
    version: int
    cvm_document_id: int | None
    received_at: date
    document_url: str | None

    @property
    def key(self) -> tuple[date, int]:
        return (self.reference_date, self.version)


@dataclass(frozen=True)
class Fact:
    reference_date: date
    version: int
    statement: str
    statement_column: str
    basis: str
    account_code: str
    account_name: str
    fixed_account: bool | None
    period_type: str
    period_start: date | None
    period_end: date
    value: Decimal
    unit: str

    @property
    def key(self) -> tuple[date, int]:
        return (self.reference_date, self.version)


@dataclass(frozen=True)
class ShareCount:
    reference_date: date
    version: int
    share_class: str
    total: int
    treasury: int

    @property
    def key(self) -> tuple[date, int]:
        return (self.reference_date, self.version)


@dataclass
class CompanyDocuments:
    doc_type: str
    filings: list[Filing] = field(default_factory=list)
    facts: list[Fact] = field(default_factory=list)
    shares: list[ShareCount] = field(default_factory=list)


def classify_period(
    doc_type: str, statement: str, start: date | None, end: date
) -> tuple[str, date | None]:
    if statement in BALANCE_SHEETS:
        return "INSTANT", None
    if start is None:
        raise CvmFormatError(f"{statement} row without DT_INI_EXERC")
    if doc_type == "DFP":
        return "FY", start
    return ("YTD" if (start.month, start.day) == (1, 1) else "3M"), start


def _fact(row: dict[str, str], doc_type: str, statement: str, basis: str) -> Fact:
    if row["MOEDA"] != "REAL":
        raise CvmFormatError(f"unsupported currency {row['MOEDA']!r}")
    scale = SCALES.get(row["ESCALA_MOEDA"])
    if scale is None:
        raise CvmFormatError(f"unsupported scale {row['ESCALA_MOEDA']!r}")
    code = row["CD_CONTA"]
    per_share = statement == "DRE" and code.startswith("3.99")
    raw_value = Decimal(row["VL_CONTA"])
    period_type, start = classify_period(
        doc_type, statement, _optional_date(row.get("DT_INI_EXERC")), _date(row["DT_FIM_EXERC"])
    )
    fixed = row.get("ST_CONTA_FIXA")
    return Fact(
        reference_date=_date(row["DT_REFER"]),
        version=int(row["VERSAO"]),
        statement=statement,
        statement_column=row.get("COLUNA_DF", ""),
        basis="consolidated" if basis == "con" else "individual",
        account_code=code,
        account_name=row["DS_CONTA"],
        fixed_account=None if not fixed else fixed == "S",
        period_type=period_type,
        period_start=start,
        period_end=_date(row["DT_FIM_EXERC"]),
        value=raw_value if per_share else raw_value * scale,
        unit="BRL/share" if per_share else "BRL",
    )


def _share_counts(row: dict[str, str]) -> Iterable[ShareCount]:
    ref, version = _date(row["DT_REFER"]), int(row["VERSAO"])
    pairs = [
        ("ON", row["QT_ACAO_ORDIN_CAP_INTEGR"], row["QT_ACAO_ORDIN_TESOURO"]),
        ("PN", row["QT_ACAO_PREF_CAP_INTEGR"], row["QT_ACAO_PREF_TESOURO"]),
    ]
    for share_class, total, treasury in pairs:
        if int(total or 0) > 0:
            yield ShareCount(ref, version, share_class, int(total), int(treasury or 0))


def parse_documents(zip_path: Path, doc_type: str, cnpj: str) -> CompanyDocuments:
    """Filings, facts and share counts of one company in a yearly DFP or ITR file."""
    prefix = f"{format_cnpj(cnpj)};".encode(ENCODING)
    docs = CompanyDocuments(doc_type=doc_type)
    with ZipFile(zip_path) as zf:
        for name in sorted(zf.namelist()):
            if _MAIN_FILE.match(name):
                with zf.open(name) as fh:
                    for row in read_rows(fh, prefix=prefix):
                        docs.filings.append(
                            Filing(
                                doc_type=doc_type,
                                reference_date=_date(row["DT_REFER"]),
                                version=int(row["VERSAO"]),
                                cvm_document_id=int(row["ID_DOC"]) if row.get("ID_DOC") else None,
                                received_at=_date(row["DT_RECEB"]),
                                document_url=row.get("LINK_DOC") or None,
                            )
                        )
            elif _CAPITAL_FILE.match(name):
                with zf.open(name) as fh:
                    for row in read_rows(fh, prefix=prefix):
                        docs.shares.extend(_share_counts(row))
            elif match := _STATEMENT_FILE.match(name):
                statement, basis = match.groups()
                with zf.open(name) as fh:
                    docs.facts.extend(
                        _fact(row, doc_type, statement, basis)
                        for row in read_rows(fh, prefix=prefix)
                    )

    known = {filing.key for filing in docs.filings}
    orphans = {item.key for item in [*docs.facts, *docs.shares]} - known
    if orphans:
        raise CvmFormatError(f"rows without a filing in {zip_path.name}: {sorted(orphans)}")
    return docs


def detect_accounting_template(facts: Iterable[Fact]) -> str | None:
    """Infer the CVM statement template from the label of the first income line (DRE 3.01)."""
    labels = [
        fact.account_name.lower()
        for fact in sorted(facts, key=lambda f: (f.reference_date, f.basis == "consolidated"))
        if fact.statement == "DRE" and fact.account_code == "3.01"
    ]
    if not labels:
        return None
    label = labels[-1]
    if "intermediação financeira" in label:
        return "bank"
    if "prêmio" in label or "seguro" in label:
        return "insurance"
    return "non_financial"
