"""Adapter contract and value objects for live data feeds.

A *feed adapter* fetches a batch of quotes from one external source
and returns them as a list of :class:`FeedQuote` value objects. The
adapter has no knowledge of the database or the orchestration loop —
that lives in :mod:`app.feeds.service`. This split is deliberate so
adapters can be unit-tested with zero infrastructure.

Adapters MUST:
  - declare a ``feed_source`` attribute matching the value persisted
    in ``live_price_quotes.feed_source``;
  - implement ``async def fetch() -> FetchOutcome``;
  - never raise from ``fetch()`` for transport-level problems —
    return a ``FetchOutcome`` with ``status="failure"`` and a
    populated ``error`` field instead. Service-level orchestration
    relies on the boundary not blowing up.

The only exception is :class:`AdapterError` raised for *programmer*
errors (misconfiguration, invalid argument). Those bubble up.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


class AdapterError(Exception):
    """Programmer-error escape hatch for adapters.

    Used for misconfiguration (missing API key when one is required,
    invalid commodity_key requested). Transport / parse / rate-limit
    problems should be returned as ``FetchOutcome(status='failure')``,
    not raised — the orchestrator distinguishes the two.
    """


@dataclass(frozen=True)
class FeedQuote:
    """A single price reading produced by a feed adapter.

    Maps 1:1 onto :class:`app.models.feeds.LivePriceQuote`. Adapters
    construct these; the service layer turns them into rows.
    """

    feed_source: str
    commodity_key: str
    display_name: str
    basis_unit: str
    price_low: float
    price_high: float
    captured_at: datetime
    currency: str = "INR"
    category: Optional[str] = None
    material_slug: Optional[str] = None
    freshness_ttl_seconds: int = 24 * 3600
    source_ref: Optional[str] = None
    payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.price_low < 0:
            raise AdapterError(
                f"FeedQuote {self.feed_source}/{self.commodity_key}: "
                f"price_low={self.price_low} must be >= 0"
            )
        if self.price_high < self.price_low:
            raise AdapterError(
                f"FeedQuote {self.feed_source}/{self.commodity_key}: "
                f"price_high={self.price_high} < price_low={self.price_low}"
            )


@dataclass
class FetchOutcome:
    """Result of one ``adapter.fetch()`` call.

    ``status`` mirrors :class:`FeedRun.status` exactly so the service
    layer can pass it through to the audit row without translation.

    ``quotes`` is empty for ``failure`` / ``skipped`` outcomes.
    ``error`` is None for successful outcomes.
    """

    status: str  # 'success' | 'partial' | 'failure' | 'skipped'
    quotes: list[FeedQuote] = field(default_factory=list)
    error: Optional[str] = None
    error_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status in {"success", "partial"}


# ─────────────────────────────────────────────────────────────────────
# Adapter abstract base
# ─────────────────────────────────────────────────────────────────────


class FeedAdapter(abc.ABC):
    """Base class for every external data adapter.

    Adapters are stateless past construction — the registry stores a
    single instance and reuses it across Celery beat invocations.
    Constructor takes the resolved ``Settings`` so adapters can pull
    their own API keys / URLs / limits without re-importing config.
    """

    feed_source: str  # subclass override; persisted to live_price_quotes.feed_source
    display_name: str = ""  # human label for admin UI
    description: str = ""  # one-liner for /admin/feeds

    def __init__(self, settings: Any) -> None:
        self.settings = settings

    @abc.abstractmethod
    async def fetch(self) -> FetchOutcome:
        """Fetch the latest batch of quotes for this feed.

        Implementations MUST NOT raise for transport / parse /
        rate-limit issues — return an outcome with ``status='failure'``
        and populate ``error`` instead. This is what lets the service
        layer record a clean ``FeedRun`` row even when the upstream
        is down.
        """
