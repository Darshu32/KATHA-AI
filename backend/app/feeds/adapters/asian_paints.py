"""Asian Paints — finish vendor catalog (per-litre prices)."""

from __future__ import annotations

from typing import Any

from app.feeds.adapters._vendor import (
    VendorLiveAdapter,
    VendorSku,
    VendorStubAdapter,
)
from app.feeds.base import FeedAdapter


_CATALOG: list[VendorSku] = [
    VendorSku(
        sku="AP-ROY-LUXURY",
        display_name="Asian Paints Royale Luxury Emulsion (per L)",
        category="vendor_sku",
        basis_unit="litre",
        baseline_low=380.0,
        baseline_high=460.0,
        material_slug="paint_emulsion",
    ),
    VendorSku(
        sku="AP-APX-EXTERIOR",
        display_name="Asian Paints Apex Ultima Exterior (per L)",
        category="vendor_sku",
        basis_unit="litre",
        baseline_low=520.0,
        baseline_high=620.0,
    ),
    VendorSku(
        sku="AP-WCN-WOODTECH",
        display_name="Asian Paints Woodtech PU Stain (per L)",
        category="vendor_sku",
        basis_unit="litre",
        baseline_low=860.0,
        baseline_high=1020.0,
    ),
]


class StubAdapter(VendorStubAdapter):
    feed_source = "vendor:asian_paints"
    display_name = "Asian Paints Catalog"
    description = "Decorative + protective finishes per litre."
    vendor_slug = "asian_paints"
    catalog = _CATALOG


class LiveAdapter(VendorLiveAdapter):
    feed_source = "vendor:asian_paints"
    display_name = "Asian Paints Catalog"
    description = "Decorative + protective finishes per litre."
    vendor_slug = "asian_paints"
    catalog = _CATALOG
    catalog_url = "https://www.asianpaints.com/products/all-products.html"


def build_adapter(settings: Any, *, live: bool) -> FeedAdapter:
    cls = LiveAdapter if live else StubAdapter
    return cls(settings)
