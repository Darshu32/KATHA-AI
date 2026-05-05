"""FX adapter — USD/INR + EUR/INR for imported materials.

The cost engine multiplies imported-material prices (Italian
travertine, German hardware, Japanese veneer, …) by these rates
during BOQ assembly. A 1.5% drift compounds into a five-figure
delta on a luxury kitchen — fresh rates matter.

LiveAdapter
-----------
Default upstream is the public exchangerate.host JSON API, override
via ``settings.feed_fx_base_url``. Format expected::

    {"rates": {"INR": 83.22, "EUR_INR": 89.41}, "base": "USD"}

The RBI reference rates would be the canonical source (RBI publishes
a daily PDF + an HTML table) but they require a more involved scraper
+ holiday awareness; that's the next iteration. For now we ship the
generic JSON adapter and document the upgrade path in the live-feeds
doc.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.feeds.adapters._http import fetch_json
from app.feeds.base import FeedAdapter, FeedQuote, FetchOutcome


class _FXBase(FeedAdapter):
    feed_source = "fx_rbi"
    display_name = "FX Rates (USD/EUR → INR)"
    description = "Daily reference rates for imported-material conversion."


class StubAdapter(_FXBase):
    async def fetch(self) -> FetchOutcome:
        now = datetime.now(timezone.utc)
        # Stable midpoint with negligible jitter so tests have a known
        # baseline but the anomaly detector never trips on the stub.
        rates = {
            "usd_inr": 83.22,
            "eur_inr": 89.41,
        }
        quotes = [
            FeedQuote(
                feed_source=self.feed_source,
                commodity_key=key,
                display_name=key.upper().replace("_", "/"),
                material_slug=None,
                category="fx",
                basis_unit="rate",
                price_low=rate,
                price_high=rate,
                captured_at=now,
                freshness_ttl_seconds=24 * 3600,
                source_ref="stub:fx",
                payload={"mode": "stub"},
            )
            for key, rate in rates.items()
        ]
        return FetchOutcome(status="success", quotes=quotes)


class LiveAdapter(_FXBase):
    async def fetch(self) -> FetchOutcome:
        url = self.settings.feed_fx_base_url
        if not url:
            return FetchOutcome(
                status="failure",
                error="feed_fx_base_url not configured",
            )

        data, error = await fetch_json(
            url,
            settings=self.settings,
            params={"base": "USD", "symbols": "INR,EUR"},
        )
        if error or data is None:
            return FetchOutcome(
                status="failure",
                error=error or "empty response",
            )

        rates = (data.get("rates") or {}) if isinstance(data, dict) else {}
        try:
            usd_inr = float(rates.get("INR"))
            eur_inr = float(rates.get("INR")) / float(rates.get("EUR"))
        except (TypeError, ValueError, ZeroDivisionError) as exc:
            return FetchOutcome(
                status="failure",
                error=f"could not derive rates: {exc}",
                error_payload={"raw_rates": rates},
            )

        now = datetime.now(timezone.utc)
        quotes = [
            FeedQuote(
                feed_source=self.feed_source,
                commodity_key="usd_inr",
                display_name="USD/INR",
                category="fx",
                basis_unit="rate",
                price_low=usd_inr,
                price_high=usd_inr,
                captured_at=now,
                freshness_ttl_seconds=24 * 3600,
                source_ref="live:exchangerate",
                payload={"raw": data},
            ),
            FeedQuote(
                feed_source=self.feed_source,
                commodity_key="eur_inr",
                display_name="EUR/INR",
                category="fx",
                basis_unit="rate",
                price_low=eur_inr,
                price_high=eur_inr,
                captured_at=now,
                freshness_ttl_seconds=24 * 3600,
                source_ref="live:exchangerate",
                payload={"raw": data},
            ),
        ]
        return FetchOutcome(status="success", quotes=quotes)


def build_adapter(settings: Any, *, live: bool) -> FeedAdapter:
    cls = LiveAdapter if live else StubAdapter
    return cls(settings)
