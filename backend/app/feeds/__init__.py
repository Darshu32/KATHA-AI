"""Stage 12 — live data feeds.

Self-updating market-data layer for the cost engine. The framework
splits cleanly into four concerns:

- :mod:`app.feeds.base`       : adapter contract + ``FeedQuote`` dataclass.
- :mod:`app.feeds.registry`   : adapter registry (analogous to
  :mod:`app.agents.tool` but for feeds).
- :mod:`app.feeds.freshness`  : how old is too old? Used by both the
  cost-engine snapshot banner ("Last priced: 2 hrs ago") and the
  fallback chain (rejecting expired cached rows).
- :mod:`app.feeds.anomaly`    : detect >threshold% midpoint moves.
- :mod:`app.feeds.fallback`   : Live → cached → seed → unavailable.
- :mod:`app.feeds.slack`      : best-effort webhook notification.
- :mod:`app.feeds.service`    : the orchestrator Celery beat calls.

Adapters live in :mod:`app.feeds.adapters` — every one ships in two
modes: a ``LiveAdapter`` that talks to the external HTTP API and a
``StubAdapter`` that returns deterministic fixtures for offline dev /
the test suite. Selection is driven by ``settings.live_feeds_enabled``.
"""

from app.feeds.base import (
    AdapterError,
    FeedAdapter,
    FeedQuote,
    FetchOutcome,
)
from app.feeds.fallback import ResolvedPrice, resolve_price_for_material
from app.feeds.freshness import (
    FreshnessLevel,
    classify_freshness,
    seconds_since,
)
from app.feeds.registry import FeedRegistry, get_registry

__all__ = [
    "AdapterError",
    "FeedAdapter",
    "FeedQuote",
    "FeedRegistry",
    "FetchOutcome",
    "FreshnessLevel",
    "ResolvedPrice",
    "classify_freshness",
    "get_registry",
    "resolve_price_for_material",
    "seconds_since",
]
