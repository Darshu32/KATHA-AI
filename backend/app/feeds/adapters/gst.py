"""GST (CBIC) adapter — material classification → tax rate.

GST rates change rarely (annual budget at most) but when they
*do* change the cost engine needs to roll over without a manual
seed update. This adapter pulls the current HSN/SAC → rate mapping
for the small set of categories the cost engine cares about
(timber, metals, ceramics, sanitaryware, textiles, paint).

Stored as percent values (``basis_unit='pct'``) inside
``live_price_quotes``. Downstream (cost-engine prompt / tax
line-item) reads them via ``get_active(feed_source='gst_cbic',
commodity_key='hsn_4407')``.

LiveAdapter
-----------
The CBIC GST rate finder is HTML-based and would need a parser.
Until that ships we expose the live adapter as a JSON consumer of a
configurable internal mirror — ops can stand up a tiny scraper
service and point ``settings.feed_gst_base_url`` at it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.feeds.adapters._http import fetch_json
from app.feeds.base import FeedAdapter, FeedQuote, FetchOutcome


_GST_CATALOG: list[dict[str, Any]] = [
    # HSN, display name, baseline GST %
    {
        "commodity_key": "hsn_4407",
        "display_name": "Sawn Timber (HSN 4407)",
        "baseline_pct": 18.0,
    },
    {
        "commodity_key": "hsn_7308",
        "display_name": "Iron/Steel Structures (HSN 7308)",
        "baseline_pct": 18.0,
    },
    {
        "commodity_key": "hsn_6907",
        "display_name": "Ceramic Tiles (HSN 6907)",
        "baseline_pct": 18.0,
    },
    {
        "commodity_key": "hsn_6910",
        "display_name": "Sanitary Ware (HSN 6910)",
        "baseline_pct": 18.0,
    },
    {
        "commodity_key": "hsn_3208",
        "display_name": "Paints / Varnishes (HSN 3208)",
        "baseline_pct": 18.0,
    },
    {
        "commodity_key": "hsn_5407",
        "display_name": "Synthetic Fabrics (HSN 5407)",
        "baseline_pct": 12.0,
    },
]


class _GSTBase(FeedAdapter):
    feed_source = "gst_cbic"
    display_name = "GST Rates (CBIC)"
    description = "Current GST percentage per HSN code for cost-engine taxes."


class StubAdapter(_GSTBase):
    async def fetch(self) -> FetchOutcome:
        now = datetime.now(timezone.utc)
        quotes = [
            FeedQuote(
                feed_source=self.feed_source,
                commodity_key=spec["commodity_key"],
                display_name=spec["display_name"],
                category="gst",
                basis_unit="pct",
                price_low=spec["baseline_pct"],
                price_high=spec["baseline_pct"],
                captured_at=now,
                freshness_ttl_seconds=30 * 86400,  # GST changes rarely
                source_ref="stub:cbic",
                payload={"mode": "stub"},
            )
            for spec in _GST_CATALOG
        ]
        return FetchOutcome(status="success", quotes=quotes)


class LiveAdapter(_GSTBase):
    async def fetch(self) -> FetchOutcome:
        url = self.settings.feed_gst_base_url
        if not url:
            return FetchOutcome(
                status="failure",
                error="feed_gst_base_url not configured",
            )

        data, error = await fetch_json(url, settings=self.settings)
        if error or data is None:
            return FetchOutcome(
                status="failure",
                error=error or "empty response",
            )

        items = (data.get("rates") or []) if isinstance(data, dict) else []
        spec_by_key = {s["commodity_key"]: s for s in _GST_CATALOG}
        quotes: list[FeedQuote] = []
        per_quote_errors: list[dict[str, Any]] = []
        seen: set[str] = set()
        now = datetime.now(timezone.utc)

        for raw in items:
            key = (raw or {}).get("hsn") or (raw or {}).get("commodity_key")
            if key and not key.startswith("hsn_"):
                key = f"hsn_{key}"
            spec = spec_by_key.get(key) if key else None
            if spec is None:
                continue
            try:
                pct = float(raw["pct"])
                quotes.append(
                    FeedQuote(
                        feed_source=self.feed_source,
                        commodity_key=spec["commodity_key"],
                        display_name=spec["display_name"],
                        category="gst",
                        basis_unit="pct",
                        price_low=pct,
                        price_high=pct,
                        captured_at=now,
                        freshness_ttl_seconds=30 * 86400,
                        source_ref=f"cbic:{spec['commodity_key']}",
                        payload={"raw": raw},
                    )
                )
                seen.add(spec["commodity_key"])
            except (KeyError, TypeError, ValueError) as exc:
                per_quote_errors.append({"hsn": key, "error": str(exc)})

        if not quotes:
            return FetchOutcome(
                status="failure",
                error="no usable GST rates in upstream payload",
                error_payload={"per_quote_errors": per_quote_errors},
            )

        missing = sorted(set(spec_by_key) - seen)
        status = "success" if not (missing or per_quote_errors) else "partial"
        return FetchOutcome(
            status=status,
            quotes=quotes,
            error=None if status == "success" else "missing or malformed entries",
            error_payload={"missing": missing, "per_quote_errors": per_quote_errors},
        )


def build_adapter(settings: Any, *, live: bool) -> FeedAdapter:
    cls = LiveAdapter if live else StubAdapter
    return cls(settings)
