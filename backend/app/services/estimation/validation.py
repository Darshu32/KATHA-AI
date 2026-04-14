"""Estimate validation routines."""

from __future__ import annotations

from decimal import Decimal

from app.services.estimation.breakdown import compute_total_from_breakdown
from app.services.estimation.models import PricedItem, round_money, to_decimal


def validate_estimate_payload(
    priced_items: list[PricedItem],
    breakdown: list[dict],
    subtotal: Decimal,
    pricing_config: dict,
    pricing_context: dict,
    pricing_adjustments: dict,
    currency_system: dict,
    fallback_state: dict,
    final_cost_per_sqft: Decimal,
    confidence_weights: dict,
    fx_service: dict,
    fx_fallback: dict,
    scenarios: list[dict],
    pricing_control: dict,
    audit_config: dict,
) -> list[str]:
    errors: list[str] = []
    material_multipliers = pricing_config["material_multipliers"]
    quality_multipliers = pricing_config["quality_multipliers"]
    style_multipliers = pricing_config["style_multipliers"]

    for item in priced_items:
        if item.quantity <= 0:
            errors.append(f"{item.item}: quantity must be greater than 0")
        if item.unit_cost < 0 or item.total_cost < 0:
            errors.append(f"{item.item}: costs must be non-negative")

        expected_total = round_money(item.unit_cost * item.quantity)
        if expected_total != round_money(item.total_cost):
            errors.append(f"{item.item}: total cost does not match unit cost x quantity")

        expected_quality = quality_multipliers.get(item.quality, quality_multipliers["standard"])
        expected_style = style_multipliers.get(item.style_tier, style_multipliers["standard"])
        expected_material = material_multipliers.get(
            str(item.material or "default").lower(),
            material_multipliers["default"],
        )
        expected_unit_cost = round_money(
            item.base_unit_cost
            * pricing_context["price_index"]
            * expected_quality
            * expected_style
            * expected_material
            * (Decimal("1") + pricing_context["market_variation"])
        )
        if expected_unit_cost != round_money(item.unit_cost):
            errors.append(f"{item.item}: pricing config or regional multiplier was applied incorrectly")

    breakdown_total = compute_total_from_breakdown(breakdown)
    if breakdown_total != round_money(subtotal):
        errors.append("Breakdown totals do not match subtotal")

    for entry in breakdown:
        if to_decimal(entry.get("quantity")) <= 0:
            errors.append(f"{entry.get('item', 'unknown')}: breakdown quantity must be greater than 0")
        if to_decimal(entry.get("unit_cost")) < 0 or to_decimal(entry.get("total_cost")) < 0:
            errors.append(f"{entry.get('item', 'unknown')}: breakdown cost values must be non-negative")

    tax_amount = round_money(subtotal * to_decimal(pricing_adjustments["tax"]))
    discount_amount = round_money(subtotal * to_decimal(pricing_adjustments["discount"]))
    expected_final_total = round_money(subtotal + tax_amount - discount_amount)
    if expected_final_total != round_money(to_decimal(pricing_adjustments["final_total"])):
        errors.append("Pricing adjustments final total is inconsistent with subtotal, tax, and discount")

    if fallback_state.get("triggered"):
        if not any(item.source == "fallback" for item in priced_items):
            errors.append("Fallback was marked as triggered but no fallback items were created")
        if final_cost_per_sqft <= 0:
            errors.append("Fallback was triggered but cost per sqft is invalid")

    conversion_rates = currency_system.get("conversion_rates", {})
    if to_decimal(conversion_rates.get(currency_system.get("base_currency", "INR"), 0)) != Decimal("1.00"):
        errors.append("Base currency conversion rate must equal 1.00")
    for code in currency_system.get("supported_currencies", []):
        if to_decimal(conversion_rates.get(code, 0)) <= 0:
            errors.append(f"Currency conversion rate missing or invalid for {code}")

    if fx_service.get("provider") == "external_api":
        has_live_rate = bool(currency_system.get("conversion_rates"))
        if not has_live_rate and not fx_fallback.get("used"):
            errors.append("FX service unavailable and fallback rates were not used")
        if fx_fallback.get("used") and not fx_fallback.get("enabled"):
            errors.append("FX fallback was used even though it is disabled")

    total_weight = sum((to_decimal(value) for value in confidence_weights.values()), Decimal("0"))
    if confidence_weights and round_money(total_weight) != Decimal("1.00"):
        errors.append("Confidence weights must sum to 1.00")

    if scenarios:
        scenario_totals = {entry["name"]: to_decimal(entry["total"]) for entry in scenarios}
        if "budget" in scenario_totals and "standard" in scenario_totals and scenario_totals["budget"] > scenario_totals["standard"]:
            errors.append("Budget scenario total cannot exceed standard scenario total")
        if "premium" in scenario_totals and "standard" in scenario_totals and scenario_totals["premium"] < scenario_totals["standard"]:
            errors.append("Premium scenario total cannot be less than standard scenario total")

    if pricing_control.get("versioned") and not pricing_control.get("version"):
        errors.append("Pricing control must include a version when versioning is enabled")

    if audit_config.get("enabled") and not audit_config.get("logs"):
        errors.append("Audit logging is enabled but no audit events are configured")

    return errors
