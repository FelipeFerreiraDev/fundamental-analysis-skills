"""Parsing Banco Central SGS series and brapi quotes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

# SGS series used by the analyses. Values are published in percent and stored as fractions.
SGS_SERIES = {
    432: ("bcb_sgs_432", "Meta Selic definida pelo Copom (% a.a.)"),
    433: ("bcb_sgs_433", "IPCA - variação mensal (%)"),
}
# Daily series accept at most 10 years per request.
SGS_WINDOW_YEARS = 5


class MacroFormatError(ValueError):
    pass


@dataclass(frozen=True)
class MacroPoint:
    series_code: str
    ref_date: date
    value: Decimal


def sgs_windows(start: date, end: date) -> list[tuple[date, date]]:
    windows = []
    current = start
    while current <= end:
        stop = min(date(current.year + SGS_WINDOW_YEARS - 1, 12, 31), end)
        windows.append((current, stop))
        current = date(stop.year + 1, 1, 1)
    return windows


def sgs_url(base: str, code: int, start: date, end: date) -> str:
    return (
        f"{base}/bcdata.sgs.{code}/dados?formato=json"
        f"&dataInicial={start:%d/%m/%Y}&dataFinal={end:%d/%m/%Y}"
    )


def parse_sgs(payload: list, code: int, *, until: date) -> list[MacroPoint]:
    """Points up to `until` (the Selic target series also lists future days)."""
    series_code, _ = SGS_SERIES[code]
    if not isinstance(payload, list):
        raise MacroFormatError(f"unexpected SGS response for series {code}")
    points = []
    for item in payload:
        ref_date = datetime.strptime(item["data"], "%d/%m/%Y").date()
        if ref_date > until:
            continue
        points.append(MacroPoint(series_code, ref_date, Decimal(item["valor"]) / Decimal(100)))
    return points


@dataclass(frozen=True)
class Quote:
    ticker: str
    quoted_at: datetime
    price: Decimal


def brapi_quote_url(base: str, ticker: str) -> str:
    return f"{base}/quote/{ticker}"


def parse_brapi_quote(payload: dict, ticker: str) -> Quote:
    results = payload.get("results") or []
    match = next((r for r in results if r.get("symbol", "").upper() == ticker.upper()), None)
    if match is None or match.get("regularMarketPrice") is None:
        raise MacroFormatError(f"brapi response without a price for {ticker}: {payload}")
    if match.get("currency", "BRL") != "BRL":
        raise MacroFormatError(f"unexpected currency {match.get('currency')!r}")
    quoted_at = datetime.fromisoformat(match["regularMarketTime"].replace("Z", "+00:00"))
    return Quote(
        ticker=ticker.upper(),
        quoted_at=quoted_at.astimezone(UTC).replace(tzinfo=None),
        price=Decimal(str(match["regularMarketPrice"])),
    )
