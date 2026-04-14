"""Config-driven pricing rule loader."""

from __future__ import annotations

from decimal import Decimal

from app.services.estimation.catalog import DEFAULT_PRICING_CONFIG
from app.services.estimation.models import to_decimal


def load_pricing_config(graph_data: dict) -> dict:
    raw_config = graph_data.get("pricing_config", {})
    return {
        "material_multipliers": _normalize_decimal_map(
            raw_config.get("material_multipliers"),
            DEFAULT_PRICING_CONFIG["material_multipliers"],
        ),
        "style_multipliers": _normalize_decimal_map(
            raw_config.get("style_multipliers"),
            DEFAULT_PRICING_CONFIG["style_multipliers"],
        ),
        "quality_multipliers": _normalize_decimal_map(
            raw_config.get("quality_multipliers"),
            DEFAULT_PRICING_CONFIG["quality_multipliers"],
        ),
        "regional_price_index": _normalize_decimal_map(
            raw_config.get("regional_price_index"),
            DEFAULT_PRICING_CONFIG["regional_price_index"],
        ),
        "market_variation_default": to_decimal(
            raw_config.get("market_variation_default"),
            DEFAULT_PRICING_CONFIG["market_variation_default"],
        ),
        "tax_default": to_decimal(
            raw_config.get("tax_default"),
            DEFAULT_PRICING_CONFIG["tax_default"],
        ),
        "discount_default": to_decimal(
            raw_config.get("discount_default"),
            DEFAULT_PRICING_CONFIG["discount_default"],
        ),
    }


def serialize_pricing_config(pricing_config: dict) -> dict:
    return {
        "material_multipliers": _serialize_decimal_map(pricing_config["material_multipliers"]),
        "style_multipliers": _serialize_decimal_map(pricing_config["style_multipliers"]),
        "quality_multipliers": _serialize_decimal_map(pricing_config["quality_multipliers"]),
        "regional_price_index": _serialize_decimal_map(pricing_config["regional_price_index"]),
        "market_variation_default": float(pricing_config["market_variation_default"]),
        "tax_default": float(pricing_config["tax_default"]),
        "discount_default": float(pricing_config["discount_default"]),
    }


def _normalize_decimal_map(raw_map: dict | None, defaults: dict) -> dict[str, Decimal]:
    normalized = {str(key).lower(): to_decimal(value) for key, value in defaults.items()}
    if not isinstance(raw_map, dict):
        return normalized

    for key, value in raw_map.items():
        normalized[str(key).lower()] = to_decimal(value)
    return normalized


def _serialize_decimal_map(values: dict[str, Decimal]) -> dict[str, float]:
    return {key: float(value) for key, value in values.items()}
