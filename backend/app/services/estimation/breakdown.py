"""Estimate payload builders."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.services.estimation.models import PricedItem, decimal_to_float, round_money, to_decimal


def build_breakdown(priced_items: list[PricedItem]) -> list[dict]:
    breakdown: list[dict] = []
    for item in priced_items:
        breakdown.append(
            {
                "item": item.item,
                "category": item.category,
                "subcategory": item.subcategory or item.category,
                "unit_cost": decimal_to_float(item.unit_cost),
                "quantity": float(item.quantity),
                "total_cost": decimal_to_float(item.total_cost),
                "currency": item.currency,
                "unit": item.unit,
                "material": item.material,
                "quality": item.quality,
                "style": item.style_tier,
                "price_factors": {key: float(value) for key, value in item.factors.items()},
                "source": item.source,
            }
        )
    return breakdown


def build_estimate_sections(priced_items: list[PricedItem]) -> dict:
    grouped: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for item in priced_items:
        grouped[item.category] += item.total_cost

    return {
        "materials": _build_section(grouped["materials"]),
        "furniture": _build_section(grouped["furniture"]),
        "labor": _build_section(grouped["labor"]),
        "services": _build_section(grouped["services"]),
        "misc": _build_section(grouped["misc"]),
    }


def build_legacy_line_items(priced_items: list[PricedItem], market_variation: Decimal) -> list[dict]:
    market_variation = max(market_variation, Decimal("0.01"))
    legacy_items: list[dict] = []

    for item in priced_items:
        low_rate = round_money(item.unit_cost * (Decimal("1") - market_variation))
        high_rate = round_money(item.unit_cost * (Decimal("1") + market_variation))

        legacy_items.append(
            {
                "category": item.subcategory or item.category,
                "item_name": item.item,
                "material": item.material,
                "quantity": float(item.quantity),
                "unit": item.unit,
                "unit_rate_low": decimal_to_float(low_rate),
                "unit_rate_high": decimal_to_float(high_rate),
                "total_low": decimal_to_float(round_money(low_rate * item.quantity)),
                "total_high": decimal_to_float(round_money(high_rate * item.quantity)),
            }
        )

    return legacy_items


def compute_total_from_breakdown(breakdown: list[dict]) -> Decimal:
    return round_money(sum((to_decimal(item["total_cost"]) for item in breakdown), Decimal("0")))


def _build_section(value: Decimal) -> dict:
    rounded = round_money(value)
    return {
        "total_cost": float(rounded),
        "currency": "INR",
    }
