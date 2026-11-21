"""Builders of synthetic B3 / BCB / brapi payloads. Values do not describe any real company."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


def cotahist_line(
    day: str,
    ticker: str,
    close_cents: int,
    *,
    market: str = "010",
    factor: int = 1,
    isin: str = "BRTESTACNOR1",
) -> str:
    price = f"{close_cents:013d}"
    line = (
        "01"
        + day
        + "02"
        + ticker.ljust(12)
        + market
        + "TESTE".ljust(12)
        + "ON      NM"
        + "   "
        + "R$  "
        + price * 4  # open, high, low, average
        + price  # close
        + "0" * 13 * 2  # best bid / ask
        + "00042"  # trades
        + "0" * 18  # quantity
        + "000000000001234500"  # volume (16v99)
        + "0" * 13
        + "0"
        + "99991231"
        + f"{factor:07d}"
        + "0" * 13
        + isin
        + "340"
    )
    assert len(line) == 245, len(line)
    return line


def write_cotahist(path: Path, lines: list[str]) -> Path:
    header = "00COTAHIST.2026BOVESPA 20261119".ljust(245)
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("COTAHIST_A2026.TXT", "\n".join([header, *lines]) + "\n")
    return path


def write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


SUPPLEMENT = [
    {
        "tradingName": "TESTE",
        "code": "TEST",
        "cashDividends": [
            {
                "isinCode": "BRTESTACNOR1",
                "paymentDate": "11/09/2026",
                "rate": "0,10245643978",
                "relatedTo": "2º Trimestre/2026",
                "approvedOn": "10/08/2026",
                "label": "JRS CAP PROPRIO",
                "lastDatePrior": "01/09/2026",
            }
        ],
        "stockDividends": [
            {
                "isinCode": "BRTESTACNOR1",
                "factor": "100,00000000000",
                "approvedOn": "02/02/2024",
                "label": "DESDOBRAMENTO",
                "lastDatePrior": "15/04/2024",
            },
            {
                "isinCode": "BRTESTACNOR1",
                "factor": "0,00100000000",
                "approvedOn": "12/11/2003",
                "label": "GRUPAMENTO",
                "lastDatePrior": "23/01/2004",
            },
            {
                "isinCode": "BRTESTA04OR1",
                "factor": "100,00000000000",
                "approvedOn": "02/02/2024",
                "label": "DESDOBRAMENTO",
                "lastDatePrior": "15/04/2024",
            },
            {
                "isinCode": "BRTESTACNOR1",
                "factor": "10,0",
                "approvedOn": "01/01/2010",
                "label": "BONIFICAÇÃO",
                "lastDatePrior": "05/01/2010",
            },
        ],
    }
]


def cash_page(results: list[dict], page: int = 1, total_pages: int = 1) -> dict:
    return {
        "page": {
            "pageNumber": page,
            "pageSize": 120,
            "totalRecords": 99,
            "totalPages": total_pages,
        },
        "results": results,
    }


def cash_item(kind: str, value: str, record: str, approved: str, type_stock: str = "ON") -> dict:
    return {
        "typeStock": type_stock,
        "dateApproval": approved,
        "valueCash": value,
        "corporateAction": kind,
        "lastDatePriorEx": record,
    }
