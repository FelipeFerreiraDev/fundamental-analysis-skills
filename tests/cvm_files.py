"""Builders of small synthetic files in the CVM open-data layout (latin-1, ';').

Values are synthetic and do not describe any real company.
"""

from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from engine.ingest.http import RemoteFile, RemoteMetadata

BANK = "00.000.000/0001-91"
OTHER = "11.111.111/0001-11"

STATEMENT_HEADER = (
    "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
    "DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA"
)
BALANCE_HEADER = (
    "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;GRUPO_DFP;MOEDA;ESCALA_MOEDA;ORDEM_EXERC;"
    "DT_FIM_EXERC;CD_CONTA;DS_CONTA;VL_CONTA;ST_CONTA_FIXA"
)
MAIN_HEADER = "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;CD_CVM;CATEG_DOC;ID_DOC;DT_RECEB;LINK_DOC"
CAPITAL_HEADER = (
    "CNPJ_CIA;DT_REFER;VERSAO;DENOM_CIA;QT_ACAO_ORDIN_CAP_INTEGR;QT_ACAO_PREF_CAP_INTEGR;"
    "QT_ACAO_TOTAL_CAP_INTEGR;QT_ACAO_ORDIN_TESOURO;QT_ACAO_PREF_TESOURO;QT_ACAO_TOTAL_TESOURO"
)
CAD_HEADER = (
    "CNPJ_CIA;DENOM_SOCIAL;DENOM_COMERC;DT_REG;DT_CONST;DT_CANCEL;MOTIVO_CANCEL;SIT;DT_INI_SIT;"
    "CD_CVM;SETOR_ATIV;TP_MERC;CATEG_REG;DT_INI_CATEG;SIT_EMISSOR;DT_INI_SIT_EMISSOR;"
    "CONTROLE_ACIONARIO"
)
FCA_HEADER = (
    "CNPJ_Companhia;Data_Referencia;Versao;ID_Documento;Nome_Empresarial;Valor_Mobiliario;"
    "Sigla_Classe_Acao_Preferencial;Classe_Acao_Preferencial;Codigo_Negociacao;"
    "Composicao_BDR_Unit;Mercado;Sigla_Entidade_Administradora;Entidade_Administradora;"
    "Data_Inicio_Negociacao;Data_Fim_Negociacao;Segmento;Data_Inicio_Listagem;Data_Fim_Listagem"
)


def dre(cnpj, ref, version, start, end, code, name, value, scale="MIL", currency="REAL"):
    return (
        f"{cnpj};{ref};{version};BANCO TESTE;001023;DF Consolidado - DRE;{currency};{scale};"
        f"ÚLTIMO;{start};{end};{code};{name};{value};S"
    )


def balance(cnpj, ref, version, end, code, name, value):
    return (
        f"{cnpj};{ref};{version};BANCO TESTE;001023;DF Consolidado - BP;REAL;MIL;ÚLTIMO;"
        f"{end};{code};{name};{value};S"
    )


def main_row(cnpj, ref, version, doc_type, doc_id, received):
    return f"{cnpj};{ref};{version};BANCO TESTE;001023;{doc_type};{doc_id};{received};http://rad/x"


def capital(cnpj, ref, version, on, pn, on_treasury, pn_treasury):
    return (
        f"{cnpj};{ref};{version};BANCO TESTE;{on};{pn};{on + pn};{on_treasury};{pn_treasury};"
        f"{on_treasury + pn_treasury}"
    )


def write_zip(path: Path, members: dict[str, list[str]]) -> Path:
    with zipfile.ZipFile(path, "w") as zf:
        for name, lines in members.items():
            zf.writestr(name, ("\n".join(lines) + "\n").encode("latin-1"))
    return path


def write_csv(path: Path, lines: list[str]) -> Path:
    path.write_bytes(("\n".join(lines) + "\n").encode("latin-1"))
    return path


@dataclass
class FakeFetcher:
    """Serves local files as if they were remote URLs; `etags` simulates file changes."""

    files: dict[str, Path] = field(default_factory=dict)
    etags: dict[str, str] = field(default_factory=dict)
    downloads: list[str] = field(default_factory=list)

    def metadata(self, url: str) -> RemoteMetadata | None:
        if url not in self.files:
            return None
        return RemoteMetadata(url, self.etags.get(url, "v1"), datetime(2026, 11, 15))

    def fetch(self, url: str) -> RemoteFile:
        if url not in self.files:
            raise FileNotFoundError(url)
        self.downloads.append(url)
        path = self.files[url]
        return RemoteFile(
            url=url,
            path=path,
            sha256="0" * 64,
            size_bytes=path.stat().st_size,
            etag=self.etags.get(url, "v1"),
            last_modified=datetime(2026, 11, 15),
            retrieved_at=datetime(2026, 11, 21, 12),
        )
