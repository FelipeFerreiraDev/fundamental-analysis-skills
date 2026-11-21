"""Parsing B3 data: COTAHIST daily prices and corporate events from the listed-companies API.

COTAHIST is the official historical quotes file (fixed-width layout published by B3).
Corporate events come from the public API behind B3's listed-companies pages: the full
history of cash events (dividends, JCP) and the stock events (splits, reverse splits,
bonus shares). Values are stored exactly as published (JCP gross of withholding tax);
adjustments for splits are computed later and never overwrite these rows.
"""

from __future__ import annotations

import base64
import json
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zipfile import ZipFile

SPOT_MARKET = b"010"

CASH_LABELS = {"DIVIDENDO": "dividend", "JRS CAP PROPRIO": "jcp", "RENDIMENTO": "other"}
STOCK_LABELS = {
    "DESDOBRAMENTO": "split",
    "GRUPAMENTO": "reverse_split",
    "BONIFICACAO": "bonus_shares",
}
SHARE_TYPES = {"ON": "ON", "PN": "PN", "PNA": "PNA", "PNB": "PNB", "UNT": "UNIT", "UNIT": "UNIT"}


class B3FormatError(ValueError):
    """The B3 file or API response does not have the expected layout."""


# COTAHIST ------------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyPrice:
    ticker: str
    trade_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    trades: int
    isin: str


def _cotahist_price(raw: bytes, quote_factor: int) -> Decimal:
    return Decimal(int(raw)) / Decimal(100) / Decimal(quote_factor)


def parse_cotahist(zip_path: Path, tickers: set[str]) -> list[DailyPrice]:
    """Spot-market rows (TPMERC 010) of the given tickers in a COTAHIST zip."""
    keys = {ticker.upper().ljust(12).encode("ascii") for ticker in tickers}
    prices: dict[tuple[str, date], DailyPrice] = {}
    with ZipFile(zip_path) as zf:
        members = [name for name in zf.namelist() if name.upper().endswith(".TXT")]
        if len(members) != 1:
            raise B3FormatError(f"{zip_path.name}: expected one .TXT member, found {members}")
        with zf.open(members[0]) as fh:
            for line in fh:
                if line[:2] != b"01" or line[12:24] not in keys or line[24:27] != SPOT_MARKET:
                    continue
                factor = int(line[210:217])
                price = DailyPrice(
                    ticker=line[12:24].decode("ascii").strip(),
                    trade_date=datetime.strptime(line[2:10].decode("ascii"), "%Y%m%d").date(),
                    open=_cotahist_price(line[56:69], factor),
                    high=_cotahist_price(line[69:82], factor),
                    low=_cotahist_price(line[82:95], factor),
                    close=_cotahist_price(line[108:121], factor),
                    volume=Decimal(int(line[170:188])) / Decimal(100),
                    trades=int(line[147:152]),
                    isin=line[230:242].decode("ascii").strip(),
                )
                key = (price.ticker, price.trade_date)
                if key in prices:
                    raise B3FormatError(f"duplicated spot quote for {key}")
                prices[key] = price
    return sorted(prices.values(), key=lambda p: (p.ticker, p.trade_date))


# Listed-companies API ------------------------------------------------------------------


def encode_params(params: dict) -> str:
    """The API takes its parameters as base64-encoded JSON in the URL path."""
    return base64.b64encode(json.dumps(params, separators=(",", ":")).encode()).decode()


def supplement_url(base: str, issuer: str) -> str:
    params = encode_params({"issuingCompany": issuer, "language": "pt-br"})
    return f"{base}/GetListedSupplementCompany/{params}"


def cash_dividends_url(base: str, trading_name: str, page: int, page_size: int = 120) -> str:
    params = encode_params(
        {
            "language": "pt-br",
            "pageNumber": page,
            "pageSize": page_size,
            "tradingName": trading_name,
        }
    )
    return f"{base}/GetListedCashDividends/{params}"


def _number(text: str) -> Decimal:
    return Decimal(text.strip().replace(".", "").replace(",", "."))


def _br_date(text: str | None) -> date | None:
    if not text or not text.strip():
        return None
    return datetime.strptime(text.strip(), "%d/%m/%Y").date()


def _label(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return " ".join(plain.upper().split())


@dataclass(frozen=True)
class CorporateEvent:
    share_class: str
    action_type: str
    source_label: str
    declared_at: date | None
    record_date: date
    payment_date: date | None
    value_per_share: Decimal | None
    factor: Decimal | None
    related_to: str | None


@dataclass(frozen=True)
class Supplement:
    trading_name: str
    payment_details: dict[tuple[str, date, Decimal], tuple[date | None, str | None]]
    stock_events: list[dict]


def parse_supplement(payload: list | dict) -> Supplement:
    record = payload[0] if isinstance(payload, list) else payload
    if not isinstance(record, dict) or "tradingName" not in record:
        raise B3FormatError("supplement response without tradingName")
    details = {}
    for item in record.get("cashDividends") or []:
        key = (_label(item["label"]), _br_date(item["lastDatePrior"]), _number(item["rate"]))
        details[key] = (_br_date(item.get("paymentDate")), item.get("relatedTo") or None)
    return Supplement(
        trading_name=record["tradingName"].strip(),
        payment_details=details,
        stock_events=list(record.get("stockDividends") or []),
    )


def parse_cash_dividends(
    pages: list[dict], share_class: str, supplement: Supplement
) -> tuple[list[CorporateEvent], list[str]]:
    """Cash events of one share class. Returns the events and the labels that were skipped."""
    events, skipped = [], []
    for page in pages:
        for item in page.get("results") or []:
            if SHARE_TYPES.get(item.get("typeStock", "").strip().upper()) != share_class:
                continue
            label = _label(item["corporateAction"])
            action_type = CASH_LABELS.get(label)
            if action_type is None:
                skipped.append(label)
                continue
            record_date = _br_date(item["lastDatePriorEx"])
            if record_date is None:
                raise B3FormatError(f"cash event without record date: {item}")
            value = _number(item["valueCash"])
            payment_date, related_to = supplement.payment_details.get(
                (label, record_date, value), (None, None)
            )
            events.append(
                CorporateEvent(
                    share_class=share_class,
                    action_type=action_type,
                    source_label=label,
                    declared_at=_br_date(item.get("dateApproval")),
                    record_date=record_date,
                    payment_date=payment_date,
                    value_per_share=value,
                    factor=None,
                    related_to=related_to,
                )
            )
    return events, skipped


def parse_stock_events(supplement: Supplement, isin: str, share_class: str) -> list[CorporateEvent]:
    """Splits, reverse splits and bonus shares of one ISIN, as new shares per old share.

    B3 publishes splits and bonus shares as a percentage (100 = +100%, i.e. 2 for 1) and
    reverse splits as the ratio itself (0.001 = 1000 old shares become 1).
    """
    events = []
    for item in supplement.stock_events:
        if item.get("isinCode", "").strip() != isin:
            continue
        label = _label(item["label"])
        action_type = STOCK_LABELS.get(label)
        if action_type is None:
            continue
        raw = _number(item["factor"])
        factor = raw if action_type == "reverse_split" else 1 + raw / 100
        events.append(
            CorporateEvent(
                share_class=share_class,
                action_type=action_type,
                source_label=label,
                declared_at=_br_date(item.get("approvedOn")),
                record_date=_br_date(item["lastDatePrior"]),
                payment_date=None,
                value_per_share=None,
                factor=factor,
                related_to=None,
            )
        )
    return events
