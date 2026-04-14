"""Dynamic pricing rules for regional, quality, style, and market-based cost adjustments."""

from __future__ import annotations

from decimal import Decimal

from app.services.estimation.catalog import (
    DEFAULT_DISCOUNT_RATE,
    DEFAULT_MARKET_VARIATION,
    DEFAULT_TAX_RATE,
)
from app.services.estimation.models import EstimateItem, PricedItem, round_money, to_decimal


def build_pricing_context(graph_data: dict, pricing_config: dict) -> dict:
    site = graph_data.get("site", {})
    region = graph_data.get("region", {})
    style = graph_data.get("style", {})
    adjustments = graph_data.get("pricing_adjustments", {})

    city = (
        region.get("city")
        or site.get("city")
        or site.get("location")
        or graph_data.get("city")
        or "Generic"
    )
    city_key = str(city).strip().lower()
    style_primary = style.get("primary") if isinstance(style, dict) else str(style or "")
    style_tier = str(graph_data.get("style_tier") or style_primary or "standard").strip().lower()
    default_quality = str(graph_data.get("quality") or "standard").strip().lower()

    return {
        "city": str(city),
        "price_index": pricing_config["regional_price_index"].get(
            city_key,
            pricing_config["regional_price_index"]["default"],
        ),
        "style_tier": style_tier or "standard",
        "default_quality": default_quality or "standard",
        "market_variation": max(
            to_decimal(
                graph_data.get("market_variation"),
                str(pricing_config.get("market_variation_default", DEFAULT_MARKET_VARIATION)),
            ),
            Decimal("0"),
        ),
        "tax_rate": max(
            to_decimal(adjustments.get("tax"), str(pricing_config.get("tax_default", DEFAULT_TAX_RATE))),
            Decimal("0"),
        ),
        "discount_rate": max(
            min(
                to_decimal(
                    adjustments.get("discount"),
                    str(pricing_config.get("discount_default", DEFAULT_DISCOUNT_RATE)),
                ),
                Decimal("1"),
            ),
            Decimal("0"),
        ),
    }


def apply_pricing_to_items(items: list[EstimateItem], pricing_context: dict, pricing_config: dict) -> list[PricedItem]:
    priced_items: list[PricedItem] = []
    region_factor = pricing_context["price_index"]
    default_quality = pricing_context["default_quality"]
    material_multipliers = pricing_config["material_multipliers"]
    quality_multipliers = pricing_config["quality_multipliers"]
    style_multipliers = pricing_config["style_multipliers"]

    for item in items:
        quality_key = default_quality
        if item.quality in quality_multipliers and item.quality != "standard":
            quality_key = item.quality

        style_key = pricing_context["style_tier"]
        if item.style_tier in style_multipliers and item.style_tier != "standard":
            style_key = item.style_tier

        quality_factor = quality_multipliers.get(quality_key, quality_multipliers["standard"])
        style_factor = style_multipliers.get(style_key, style_multipliers["standard"])
        material_key = str(item.material or "default").strip().lower()
        material_factor = material_multipliers.get(material_key, material_multipliers.get("default", Decimal("1.00")))
        market_factor = Decimal("1") + pricing_context["market_variation"]

        unit_cost = round_money(
            item.base_unit_cost * region_factor * quality_factor * style_factor * material_factor * market_factor
        )
        total_cost = round_money(unit_cost * item.quantity)

        priced_items.append(
            PricedItem(
                item=item.item,
                category=item.category,
                quantity=item.quantity,
                unit=item.unit,
                base_unit_cost=item.base_unit_cost,
                unit_cost=unit_cost,
                total_cost=total_cost,
                currency=item.currency,
                subcategory=item.subcategory,
                material=item.material,
                quality=quality_key,
                style_tier=style_key,
                source=item.source,
                factors={
                    "region": region_factor,
                    "quality": quality_factor,
                    "style": style_factor,
                    "material": material_factor,
                    "market": market_factor,
                },
                metadata=item.metadata,
            )
        )

    return priced_items


def build_pricing_adjustments(subtotal: Decimal, pricing_context: dict) -> dict:
    tax_amount = round_money(subtotal * pricing_context["tax_rate"])
    discount_amount = round_money(subtotal * pricing_context["discount_rate"])
    final_total = round_money(subtotal + tax_amount - discount_amount)

    return {
        "tax": float(pricing_context["tax_rate"]),
        "tax_amount": float(tax_amount),
        "discount": float(pricing_context["discount_rate"]),
        "discount_amount": float(discount_amount),
        "final_total": float(final_total),
    }
