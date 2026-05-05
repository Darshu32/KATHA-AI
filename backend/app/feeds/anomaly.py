"""Detect anomalous price moves between successive feed quotes.

A price that jumps by more than ``feed_anomaly_pct_threshold``
percent between the previous current quote and the incoming one
fires an alert. The primary use case is **catching API errors** —
an MCX page that suddenly returns 1/100th of the real value, a
vendor scraper that picked up a sale price as the list price, an
FX rate flipping units. A real-world price spike is the secondary
use case.

The detector is **pure** — no DB, no IO. The service layer feeds
it the previous and new quotes (or their midpoints) and persists
the resulting :class:`AnomalyVerdict` only when ``triggered`` is
true.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.config import get_settings


@dataclass(frozen=True)
class AnomalyVerdict:
    """Result of comparing two quote midpoints.

    ``triggered`` is the only field callers branch on. The rest are
    populated for the audit row.
    """

    triggered: bool
    pct_change: float
    direction: str  # 'up' | 'down' | 'flat'
    threshold_pct: float
    previous_mid: float
    new_mid: float
    reason: str


def midpoint(low: float, high: float) -> float:
    """Standard band midpoint. Repeated enough times to deserve a name."""
    return (low + high) / 2.0


def detect_anomaly(
    *,
    previous_low: Optional[float],
    previous_high: Optional[float],
    new_low: float,
    new_high: float,
    threshold_pct: Optional[float] = None,
) -> AnomalyVerdict:
    """Compare a new price band against the previous one.

    Returns a verdict structure even when no anomaly is detected so
    the service layer can record the comparison verbatim. ``triggered``
    is the only field callers should branch on.

    A ``previous_low`` of ``None`` means there is no prior quote
    (this is the first reading) — never an anomaly.

    A ``previous_mid`` of zero is treated as "first reading" too,
    because percentage comparisons against zero are meaningless and
    the seeded baseline often comes in at a placeholder of zero
    during cold-start.
    """
    threshold = (
        threshold_pct
        if threshold_pct is not None
        else get_settings().feed_anomaly_pct_threshold
    )

    new_mid = midpoint(new_low, new_high)

    if previous_low is None or previous_high is None:
        return AnomalyVerdict(
            triggered=False,
            pct_change=0.0,
            direction="flat",
            threshold_pct=threshold,
            previous_mid=0.0,
            new_mid=new_mid,
            reason="no_previous_quote",
        )

    previous_mid = midpoint(previous_low, previous_high)
    if previous_mid == 0:
        return AnomalyVerdict(
            triggered=False,
            pct_change=0.0,
            direction="flat",
            threshold_pct=threshold,
            previous_mid=0.0,
            new_mid=new_mid,
            reason="previous_mid_zero",
        )

    delta = new_mid - previous_mid
    pct_change = (delta / previous_mid) * 100.0
    direction = "up" if delta > 0 else ("down" if delta < 0 else "flat")
    triggered = abs(pct_change) >= threshold
    reason = (
        f"|{pct_change:.2f}%| >= {threshold}%"
        if triggered
        else f"|{pct_change:.2f}%| < {threshold}%"
    )
    return AnomalyVerdict(
        triggered=triggered,
        pct_change=pct_change,
        direction=direction,
        threshold_pct=threshold,
        previous_mid=previous_mid,
        new_mid=new_mid,
        reason=reason,
    )
