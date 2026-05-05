"""Jaquar — sanitaryware vendor catalog.

Cost engine consumes Jaquar SKUs as the canonical premium-bath fixture
baseline. The stub catalog covers the four most-quoted SKUs in
Phase-1 estimates (faucet, shower, WC, bathtub).
"""

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
        sku="JAQ-FAU-001",
        display_name="Jaquar Florentine Single Lever Basin Mixer",
        category="vendor_sku",
        basis_unit="piece",
        baseline_low=12000.0,
        baseline_high=14500.0,
    ),
    VendorSku(
        sku="JAQ-SHW-101",
        display_name="Jaquar Continental Overhead Shower 200mm",
        category="vendor_sku",
        basis_unit="piece",
        baseline_low=4800.0,
        baseline_high=6200.0,
    ),
    VendorSku(
        sku="JAQ-WC-220",
        display_name="Jaquar Solo Wall-Hung WC + Concealed Tank",
        category="vendor_sku",
        basis_unit="piece",
        baseline_low=22000.0,
        baseline_high=28000.0,
    ),
    VendorSku(
        sku="JAQ-BTH-450",
        display_name="Jaquar Opal Freestanding Bathtub 1700mm",
        category="vendor_sku",
        basis_unit="piece",
        baseline_low=85000.0,
        baseline_high=110000.0,
    ),
]


class StubAdapter(VendorStubAdapter):
    feed_source = "vendor:jaquar"
    display_name = "Jaquar Catalog"
    description = "Premium sanitaryware reference SKUs."
    vendor_slug = "jaquar"
    catalog = _CATALOG


class LiveAdapter(VendorLiveAdapter):
    feed_source = "vendor:jaquar"
    display_name = "Jaquar Catalog"
    description = "Premium sanitaryware reference SKUs."
    vendor_slug = "jaquar"
    catalog = _CATALOG
    catalog_url = "https://www.jaquar.com/en/catalogue"


def build_adapter(settings: Any, *, live: bool) -> FeedAdapter:
    cls = LiveAdapter if live else StubAdapter
    return cls(settings)
