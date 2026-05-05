"""Freshness classification for live-pricing rows.

Single source of truth for "how old is this price?". The same ladder
is consumed by:

- :func:`app.feeds.fallback.resolve_price_for_material` to decide
  whether a cached row is acceptable;
- :func:`app.services.pricing.knowledge_service.build_pricing_knowledge`
  to annotate the cost-engine snapshot's ``source_versions`` block;
- the admin dashboard at ``/admin/feeds`` to colour-code per-feed status.

Bands are read from :class:`app.config.Settings` so an ops outage can
be ridden out by widening ``feed_freshness_recent_seconds`` rather
than every estimate flipping to "expired" in the UI.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from app.config import get_settings


class FreshnessLevel(str, Enum):
    """How fresh a cached price is, expressed as a UI-friendly enum.

    ``LIVE``     : within ``feed_freshness_live_seconds`` (default 6h).
    ``RECENT``   : within ``feed_freshness_recent_seconds`` (default 24h).
    ``STALE``    : within ``feed_freshness_stale_seconds`` (default 14d).
    ``EXPIRED``  : older than the stale band — fallback should reject.
    ``UNKNOWN``  : no ``captured_at`` recorded (e.g. seed rows).
    """

    LIVE = "live"
    RECENT = "recent"
    STALE = "stale"
    EXPIRED = "expired"
    UNKNOWN = "unknown"

    @property
    def is_acceptable_for_live_lookup(self) -> bool:
        """Whether the fallback chain may use a row at this freshness."""
        return self in {self.LIVE, self.RECENT, self.STALE}


def seconds_since(when: Optional[datetime]) -> Optional[float]:
    """Whole seconds between ``when`` and now (UTC). ``None`` if undated."""
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds()


def classify_freshness(captured_at: Optional[datetime]) -> FreshnessLevel:
    """Bucket a quote into one of the five :class:`FreshnessLevel` bands."""
    age = seconds_since(captured_at)
    if age is None:
        return FreshnessLevel.UNKNOWN

    s = get_settings()
    if age <= s.feed_freshness_live_seconds:
        return FreshnessLevel.LIVE
    if age <= s.feed_freshness_recent_seconds:
        return FreshnessLevel.RECENT
    if age <= s.feed_freshness_stale_seconds:
        return FreshnessLevel.STALE
    return FreshnessLevel.EXPIRED


def humanize_age(captured_at: Optional[datetime]) -> str:
    """Render the age as the UI string ("2 hrs ago", "14 days ago")."""
    age = seconds_since(captured_at)
    if age is None:
        return "unknown"
    if age < 60:
        return f"{int(age)} sec ago"
    if age < 3600:
        return f"{int(age // 60)} min ago"
    if age < 86400:
        return f"{int(age // 3600)} hrs ago"
    return f"{int(age // 86400)} days ago"


def freshness_envelope(captured_at: Optional[datetime]) -> dict:
    """Standard dict shape returned to clients with every priced row.

    Goes onto every ``source_versions`` entry so downstream code (UI,
    transparency banner) renders consistently without per-callsite
    reformatting.
    """
    return {
        "level": classify_freshness(captured_at).value,
        "age_seconds": seconds_since(captured_at),
        "age_human": humanize_age(captured_at),
        "captured_at": captured_at.isoformat() if captured_at else None,
    }
