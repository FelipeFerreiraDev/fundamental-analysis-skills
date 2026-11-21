"""Interest and inflation rate arithmetic."""

from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal


def compound(rates: Iterable[Decimal]) -> Decimal:
    """Accumulated rate of consecutive periods: (1 + r1) x (1 + r2) x ... - 1.

    Rates are fractions (0.0014 = 0.14%). An empty sequence accumulates to zero.
    """
    total = Decimal(1)
    for rate in rates:
        if rate <= -1:
            raise ValueError(f"a period rate of {rate} would wipe out the base")
        total *= 1 + rate
    return total - 1
