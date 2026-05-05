"""Shared scaffolding for vendor catalog scrapers.

Vendor scrapers are the most fragile feeds — every site has a
different layout and changes it without warning. We give each
vendor its own tiny module so a layout change is a one-file fix,
but the boilerplate (FeedQuote construction, error envelopes,
stub fixtures) lives here.

Live scrapers are intentionally minimal placeholders: they fetch
the configured catalog URL and return ``failure`` until a vendor-
specific HTML/JSON parser is wired in. This is deliberate — we
ship the framework now and replace the parser per-vendor as
business need dictates rather than guessing at brittle selectors
that'll break before the first real refresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from app.feeds.adapters._http import fetch_text
from app.feeds.base import FeedAdapter, FeedQuote, FetchOutcome


@dataclass(frozen=True)
class VendorSku:
    sku: str
    display_name: str
    category: str
    basis_unit: str
    baseline_low: float
    baseline_high: float
    material_slug: Optional[str] = None


def make_quote(
    *,
    feed_source: str,
    sku: VendorSku,
    captured_at: datetime,
    low: float,
    high: float,
    payload: dict[str, Any],
    source_ref: str,
) -> FeedQuote:
    return FeedQuote(
        feed_source=feed_source,
        commodity_key=sku.sku,
        display_name=sku.display_name,
        material_slug=sku.material_slug,
        category=sku.category,
        basis_unit=sku.basis_unit,
        price_low=low,
        price_high=high,
        captured_at=captured_at,
        freshness_ttl_seconds=7 * 86400,  # vendor catalogs settle slowly
        source_ref=source_ref,
        payload=payload,
    )


class VendorStubAdapter(FeedAdapter):
    """Deterministic offline variant — returns the SKU baselines."""

    catalog: list[VendorSku] = []
    vendor_slug: str = ""

    async def fetch(self) -> FetchOutcome:
        now = datetime.now(timezone.utc)
        quotes = [
            make_quote(
                feed_source=self.feed_source,
                sku=sku,
                captured_at=now,
                low=sku.baseline_low,
                high=sku.baseline_high,
                payload={"mode": "stub"},
                source_ref=f"stub:{self.vendor_slug}:{sku.sku}",
            )
            for sku in self.catalog
        ]
        return FetchOutcome(status="success", quotes=quotes)


class VendorLiveAdapter(FeedAdapter):
    """Live scraper scaffold.

    Fetches the configured catalog URL (HTML page) and currently
    returns ``failure`` with the raw payload size so ops sees a
    clear "implement parser" signal in ``/admin/feeds``. Subclasses
    can override :meth:`parse_html` to extract SKU prices.
    """

    catalog_url: str = ""
    vendor_slug: str = ""
    catalog: list[VendorSku] = []

    async def fetch(self) -> FetchOutcome:
        if not self.catalog_url:
            return FetchOutcome(
                status="failure",
                error=f"{self.vendor_slug} catalog_url not configured",
            )
        text, error = await fetch_text(self.catalog_url, settings=self.settings)
        if error or text is None:
            return FetchOutcome(
                status="failure",
                error=error or "empty response",
            )
        try:
            quotes = self.parse_html(text)
        except Exception as exc:  # noqa: BLE001
            return FetchOutcome(
                status="failure",
                error=f"parse_html raised: {exc}",
                error_payload={"type": type(exc).__name__},
            )
        if not quotes:
            return FetchOutcome(
                status="failure",
                error="parser returned no quotes",
                error_payload={"page_bytes": len(text)},
            )
        return FetchOutcome(status="success", quotes=quotes)

    def parse_html(self, html: str) -> list[FeedQuote]:
        """Override per-vendor. Default = parser not yet implemented."""
        raise NotImplementedError(
            f"parse_html not implemented for {self.vendor_slug}; "
            "ship the StubAdapter while the live parser is in flight."
        )
