"""MCX (Multi Commodity Exchange of India) adapter.

Pulls daily reference prices for the metals the cost engine cares
about: hot-rolled steel coil, primary aluminium, electrolytic copper.
The numbers feed straight into the cost engine's
``materials_kb.metals_inr_kg`` band — the live row supersedes the
seed row when the fallback chain runs.

LiveAdapter
-----------
The official MCX site (mcxindia.com) publishes a settlement-price
JSON endpoint. The exact URL is configured via
``settings.feed_mcx_base_url`` so a staging environment can point at
a recording proxy. We don't hard-code the canonical URL here because
MCX has changed it in the past — keeping it config-driven means a
URL bump is a one-line ops change instead of a code release.

When the URL is unset the live adapter degrades to ``failure``
(rather than guessing) so ops sees a clear "configure me" signal in
``/admin/feeds`` rather than a silent stub-mode swap.

StubAdapter
-----------
Returns the BRD baseline for the three metals with a tiny ±2% jitter
keyed by the wall clock minute. Deterministic enough for the test
suite, lively enough to verify the anomaly detector wiring during
manual smoke tests.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.feeds.adapters._http import fetch_json
from app.feeds.base import FeedAdapter, FeedQuote, FetchOutcome


# ``material_slug`` values must match seeded ``material_prices.slug``
# entries from 0003_stage1_pricing_seed; otherwise the fallback chain
# can't promote the live quote over the seed row. Verified against
# ``app.knowledge.materials.METALS`` keys.
_MCX_COMMODITIES: list[dict[str, Any]] = [
    {
        "commodity_key": "steel_hrc",
        "display_name": "Hot-Rolled Steel Coil (MCX)",
        "material_slug": "mild_steel",
        "category": "commodity",
        "basis_unit": "kg",
        "baseline_low": 60.0,
        "baseline_high": 90.0,
    },
    {
        "commodity_key": "aluminium",
        "display_name": "Primary Aluminium (MCX)",
        "material_slug": "aluminium_6061",
        "category": "commodity",
        "basis_unit": "kg",
        "baseline_low": 250.0,
        "baseline_high": 400.0,
    },
    {
        "commodity_key": "copper",
        "display_name": "Electrolytic Copper (MCX)",
        # No matching seed slug — quote stands alone in the live table.
        # When/if a copper material seed is added, populate this field.
        "material_slug": None,
        "category": "commodity",
        "basis_unit": "kg",
        "baseline_low": 780.0,
        "baseline_high": 880.0,
    },
]


class _MCXBase(FeedAdapter):
    feed_source = "mcx"
    display_name = "MCX Commodities"
    description = "Daily settlement prices for steel, aluminium, copper."


class StubAdapter(_MCXBase):
    """Deterministic offline variant for tests + dev."""

    async def fetch(self) -> FetchOutcome:
        now = datetime.now(timezone.utc)
        jitter = 1.0 + ((now.minute % 5) - 2) * 0.005  # ±1%
        quotes: list[FeedQuote] = []
        for spec in _MCX_COMMODITIES:
            quotes.append(
                FeedQuote(
                    feed_source=self.feed_source,
                    commodity_key=spec["commodity_key"],
                    display_name=spec["display_name"],
                    material_slug=spec["material_slug"],
                    category=spec["category"],
                    basis_unit=spec["basis_unit"],
                    price_low=round(spec["baseline_low"] * jitter, 2),
                    price_high=round(spec["baseline_high"] * jitter, 2),
                    captured_at=now,
                    freshness_ttl_seconds=24 * 3600,
                    source_ref="stub:mcx",
                    payload={"mode": "stub", "jitter": jitter},
                )
            )
        return FetchOutcome(status="success", quotes=quotes)


class LiveAdapter(_MCXBase):
    """Production HTTP variant.

    Expects a JSON document with the shape::

        {"prices": [{"symbol": "steel_hrc", "low": 62.0, "high": 91.0,
                     "captured_at": "2026-05-02T09:30:00Z"}, ...]}

    Mapping from upstream symbols to ``commodity_key`` is fixed by
    :data:`_MCX_COMMODITIES`. Symbols not in the mapping are ignored
    (logged at debug). Missing symbols fall through to ``partial``.
    """

    async def fetch(self) -> FetchOutcome:
        url = self.settings.feed_mcx_base_url
        if not url:
            return FetchOutcome(
                status="failure",
                error="feed_mcx_base_url not configured",
            )

        data, error = await fetch_json(url, settings=self.settings)
        if error or data is None:
            return FetchOutcome(
                status="failure",
                error=error or "empty response",
            )

        prices = (data.get("prices") or []) if isinstance(data, dict) else []
        if not prices:
            return FetchOutcome(
                status="failure",
                error="upstream returned no prices",
                error_payload={"raw_keys": list(data.keys()) if isinstance(data, dict) else []},
            )

        spec_by_key = {s["commodity_key"]: s for s in _MCX_COMMODITIES}
        quotes: list[FeedQuote] = []
        seen: set[str] = set()
        per_quote_errors: list[dict[str, Any]] = []

        for raw in prices:
            symbol = (raw or {}).get("symbol")
            spec = spec_by_key.get(symbol)
            if spec is None:
                continue
            try:
                low = float(raw["low"])
                high = float(raw["high"])
                captured_at = _parse_iso(raw.get("captured_at")) or datetime.now(
                    timezone.utc
                )
                quotes.append(
                    FeedQuote(
                        feed_source=self.feed_source,
                        commodity_key=spec["commodity_key"],
                        display_name=spec["display_name"],
                        material_slug=spec["material_slug"],
                        category=spec["category"],
                        basis_unit=spec["basis_unit"],
                        price_low=low,
                        price_high=high,
                        captured_at=captured_at,
                        freshness_ttl_seconds=24 * 3600,
                        source_ref=f"mcx:{symbol}",
                        payload={"raw": raw},
                    )
                )
                seen.add(spec["commodity_key"])
            except (KeyError, TypeError, ValueError) as exc:
                per_quote_errors.append(
                    {"symbol": symbol, "error": str(exc)}
                )

        missing = sorted(set(spec_by_key) - seen)
        status = "success"
        if not quotes:
            return FetchOutcome(
                status="failure",
                error="no usable prices in upstream payload",
                error_payload={"per_quote_errors": per_quote_errors},
            )
        if missing or per_quote_errors:
            status = "partial"

        return FetchOutcome(
            status=status,
            quotes=quotes,
            error=None if status == "success" else "missing or malformed entries",
            error_payload={
                "missing": missing,
                "per_quote_errors": per_quote_errors,
            },
        )


def build_adapter(settings: Any, *, live: bool) -> FeedAdapter:
    cls = LiveAdapter if live else StubAdapter
    return cls(settings)


def _parse_iso(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
