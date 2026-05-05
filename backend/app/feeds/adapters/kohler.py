"""Kohler — premium kitchen + bath vendor catalog."""

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
        sku="KOH-SNK-540",
        display_name="Kohler Strive Workstation Single-Bowl Sink",
        category="vendor_sku",
        basis_unit="piece",
        baseline_low=42000.0,
        baseline_high=58000.0,
    ),
    VendorSku(
        sku="KOH-FAU-220",
        display_name="Kohler Artifacts Single-Lever Kitchen Faucet",
        category="vendor_sku",
        basis_unit="piece",
        baseline_low=38000.0,
        baseline_high=52000.0,
    ),
    VendorSku(
        sku="KOH-WC-715",
        display_name="Kohler Veil One-Piece Wall-Hung WC",
        category="vendor_sku",
        basis_unit="piece",
        baseline_low=145000.0,
        baseline_high=185000.0,
    ),
]


class StubAdapter(VendorStubAdapter):
    feed_source = "vendor:kohler"
    display_name = "Kohler Catalog"
    description = "Premium kitchen + bath SKUs."
    vendor_slug = "kohler"
    catalog = _CATALOG


class LiveAdapter(VendorLiveAdapter):
    feed_source = "vendor:kohler"
    display_name = "Kohler Catalog"
    description = "Premium kitchen + bath SKUs."
    vendor_slug = "kohler"
    catalog = _CATALOG
    catalog_url = "https://www.kohler.co.in/products"


def build_adapter(settings: Any, *, live: bool) -> FeedAdapter:
    cls = LiveAdapter if live else StubAdapter
    return cls(settings)
