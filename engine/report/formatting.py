"""Brazilian number and date formatting for the report. Formatting only: no arithmetic
beyond scaling a value to the unit it is displayed in."""

from __future__ import annotations

from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal


def _grouped(value: Decimal, places: int) -> str:
    quantum = Decimal(1).scaleb(-places)
    text = f"{value.quantize(quantum, rounding=ROUND_HALF_EVEN):,.{places}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


def number(value: Decimal | int | None, places: int = 2) -> str:
    return "—" if value is None else _grouped(Decimal(value), places)


def brl(value: Decimal | None, places: int = 2) -> str:
    if value is None:
        return "—"
    sign = "−" if value < 0 else ""
    return f"{sign}R$ {_grouped(abs(Decimal(value)), places)}"


def brl_compact(value: Decimal | None) -> str:
    """Large amounts in bi / mi (R$ 11,02 bi)."""
    if value is None:
        return "—"
    value = Decimal(value)
    sign = "−" if value < 0 else ""
    magnitude = abs(value)
    for size, suffix in ((Decimal(10) ** 9, "bi"), (Decimal(10) ** 6, "mi")):
        if magnitude >= size:
            return f"{sign}R$ {_grouped(magnitude / size, 2)} {suffix}"
    return brl(value)


def percent(value: Decimal | None, places: int = 2) -> str:
    return "—" if value is None else f"{_grouped(Decimal(value) * 100, places)}%"


def multiple(value: Decimal | None) -> str:
    return "—" if value is None else f"{_grouped(Decimal(value), 2)}x"


def day(value: date | datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")
    return value.strftime("%d/%m/%Y")


def by_unit(value: Decimal, unit: str, *, kind: str = "") -> str:
    """Format a contract value by its unit (`kind` = 'multiple' for P/L-like ratios)."""
    if unit == "BRL":
        return brl_compact(value)
    if unit == "BRL/share":
        return brl(value)
    if unit == "shares":
        return number(value, 0)
    if unit == "ratio":
        return multiple(value) if kind == "multiple" else percent(value)
    return number(value)
