"""Inline SVG column charts for the report (single series, works offline and in print).

Follows the data-viz rules adopted for the project: one series per chart (the title names
it, no legend), columns at most 24px wide with a 4px rounded data end and a square end on
the baseline, hairline recessive grid, values on hover (and in the table view next to the
chart), text in text tokens and never in the series color.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from decimal import Decimal
from html import escape

from markupsafe import Markup

WIDTH, HEIGHT = 640, 240
LEFT, RIGHT, TOP, BOTTOM = 72, 96, 16, 28  # right margin holds the last value
MAX_BAR = 24
RADIUS = 4


def nice_ticks(low: float, high: float, count: int = 5) -> list[float]:
    """Round axis ticks (steps of 1, 2 or 5 x 10^n) covering [low, high] and zero."""
    low, high = min(low, 0.0), max(high, 0.0)
    if low == high:
        high = low + 1
    raw = (high - low) / max(count - 1, 1)
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 5, 10) if m * power >= raw)
    ticks = [round(math.floor(low / step) * step, 10)]
    while ticks[-1] < high:
        ticks.append(round(ticks[-1] + step, 10))
    return ticks


def _bar_path(x: float, width: float, y_base: float, y_value: float) -> str:
    """Column with rounded corners on the data end and square corners on the baseline."""
    r = min(RADIUS, width / 2, abs(y_base - y_value))
    if y_value <= y_base:  # positive: data end on top
        return (
            f"M{x:.2f},{y_base:.2f} V{y_value + r:.2f} Q{x:.2f},{y_value:.2f} {x + r:.2f},"
            f"{y_value:.2f} H{x + width - r:.2f} Q{x + width:.2f},{y_value:.2f} "
            f"{x + width:.2f},{y_value + r:.2f} V{y_base:.2f} Z"
        )
    return (  # negative: data end at the bottom
        f"M{x:.2f},{y_base:.2f} V{y_value - r:.2f} Q{x:.2f},{y_value:.2f} {x + r:.2f},"
        f"{y_value:.2f} H{x + width - r:.2f} Q{x + width:.2f},{y_value:.2f} "
        f"{x + width:.2f},{y_value - r:.2f} V{y_base:.2f} Z"
    )


def column_chart(
    title: str,
    points: list[tuple[str, Decimal]],
    *,
    axis_format: Callable[[Decimal], str],
    value_format: Callable[[Decimal], str],
    scale: Decimal = Decimal(1),
) -> Markup:
    """SVG of one series. `scale` divides values for the axis (e.g. 1e9 for billions)."""
    if not points:
        return Markup("")
    values = [float(v / scale) for _, v in points]
    ticks = nice_ticks(min(values), max(values))
    low, high = ticks[0], ticks[-1]
    plot_h = HEIGHT - TOP - BOTTOM
    plot_w = WIDTH - LEFT - RIGHT

    def y(v: float) -> float:
        return TOP + (high - v) / (high - low) * plot_h

    band = plot_w / len(points)
    bar = min(MAX_BAR, band * 0.6)
    parts = [
        f'<svg class="chart" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" '
        f'aria-label="{escape(title)}" preserveAspectRatio="xMidYMid meet">'
    ]
    for tick in ticks:
        ty = y(tick)
        css = "baseline" if tick == 0 else "grid"
        parts.append(
            f'<line class="{css}" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{ty:.2f}" y2="{ty:.2f}"/>'
        )
        label = axis_format(Decimal(str(tick)))
        parts.append(
            f'<text class="tick" x="{LEFT - 8}" y="{ty + 4:.2f}" '
            f'text-anchor="end">{escape(label)}</text>'
        )
    zero = y(0)
    for index, ((label, raw), value) in enumerate(zip(points, values, strict=True)):
        x = LEFT + band * index + (band - bar) / 2
        tip = f"{label}: {value_format(raw)}"
        parts.append('<g class="mark" tabindex="0">')
        parts.append(f"<title>{escape(tip)}</title>")
        parts.append(
            f'<rect class="hit" x="{LEFT + band * index:.2f}" y="{TOP}" '
            f'width="{band:.2f}" height="{plot_h}"/>'
        )
        if value != 0:
            parts.append(f'<path class="bar" d="{_bar_path(x, bar, zero, y(value))}"/>')
        parts.append("</g>")
        parts.append(
            f'<text class="tick" x="{x + bar / 2:.2f}" y="{HEIGHT - 8}" '
            f'text-anchor="middle">{escape(label)}</text>'
        )
    # Direct label only on the latest value, beside the column so it never overlaps a neighbor.
    _, last_raw = points[-1]
    last_x = LEFT + band * (len(points) - 1) + (band + bar) / 2 + 6
    last_y = min(max(y(values[-1]) + 4, TOP + 10), HEIGHT - BOTTOM)
    parts.append(
        f'<text class="value" x="{last_x:.2f}" y="{last_y:.2f}" '
        f'text-anchor="start">{escape(value_format(last_raw))}</text>'
    )
    parts.append("</svg>")
    return Markup("".join(parts))
