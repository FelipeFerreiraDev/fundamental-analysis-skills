"""Builders of synthetic contract values for tests. They are not real figures of any company."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

SOURCE = {
    "id": "test-dfp-2025",
    "provider": "cvm",
    "document_type": "DFP",
    "retrieved_at": datetime(2026, 11, 21, 12, 0),
    "extraction": "structured",
}


def reported(value: str, unit: str = "BRL", **overrides) -> dict:
    base = {
        "value": Decimal(value),
        "unit": unit,
        "period": {"type": "FY", "start": date(2025, 1, 1), "end": date(2025, 12, 31)},
        "basis": "consolidated",
        "nature": "reported",
        "source_ids": [SOURCE["id"]],
        "confidence": "high",
    }
    return {**base, **overrides}


def instant(value: str, unit: str, **overrides) -> dict:
    return reported(
        value, unit, period={"type": "INSTANT", "end": date(2025, 12, 31)}, basis=None, **overrides
    )
