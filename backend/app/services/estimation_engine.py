"""Enterprise-grade estimation engine with live FX, dynamic scenarios, and audit support."""

from __future__ import annotations

import logging
from decimal import Decimal

from app.services.estimation import (
    append_currency_conversions,
    apply_pricing_to_items,
    build_audit_config,
    build_breakdown,
    build_catalog_metadata,
    build_confidence_score,
    build_cost_suggestions,
    build_fx_fallback,
    build_fx_service,
    build_history_entries,
    build_history_storage,
    build_legacy_line_items,
    build_pricing_control,
    build_pricing_adjustments,
    build_pricing_context,
    build_scenario_engine,
    calculate_area_summary,
    calculate_furniture_items,
    calculate_labor_items,
    calculate_material_items,
    calculate_misc_items,
    calculate_service_items,
    emit_audit_logs,
    generate_scenarios,
    load_pricing_config,
    resolve_currency_system,
    serialize_pricing_config,
    validate_estimate_payload,
)
from app.services.estimation.breakdown import build_estimate_sections
from app.services.estimation.catalog import (
    CURRENCY,
    DEFAULT_COST_PER_SQFT_FALLBACK,
    DEFAULT_ESTIMATE_VERSION,
)
from app.services.estimation.models import EstimateItem, round_money, to_decimal

logger = logging.getLogger(__name__)

PRECISION_POLICY = {
    "rounding": "2_decimal",
    "mode": "financial_standard",
}


def process(layout: dict) -> dict:
    """Pipeline-facing estimation entry point."""
    logger.info("estimate_generated: starting estimate computation")
    return compute_estimate(layout)


def compute_estimate(graph_data: dict) -> dict:
    """Read the design graph and produce an enriched, backward-compatible estimate."""
    try:
        return _compute_estimate(graph_data)
    except Exception as exc:
        logger.exception("estimate_finalized: failed to compute estimate")
        return {
            "status": "failed",
            "errors": [str(exc)],
            "estimate_version": DEFAULT_ESTIMATE_VERSION,
            "currency": CURRENCY,
            "estimate": {
                "materials": {"total_cost": 0.0, "currency": CURRENCY},
                "furniture": {"total_cost": 0.0, "currency": CURRENCY},
                "labor": {"total_cost": 0.0, "currency": CURRENCY},
                "services": {"total_cost": 0.0, "currency": CURRENCY},
                "misc": {"total_cost": 0.0, "currency": CURRENCY},
            },
            "breakdown": [],
            "area": {"total_sqft": 0.0, "cost_per_sqft": 0.0},
            "region": {"city": "Generic", "price_index": 1.0},
            "pricing_adjustments": {
                "tax": 0.0,
                "tax_amount": 0.0,
                "discount": 0.0,
                "discount_amount": 0.0,
                "final_total": 0.0,
            },
            "confidence": {"score": 0.0, "level": "low", "factors": []},
            "export": {"pdf_ready": False, "invoice_ready": False, "excel_ready": False},
            "assumptions": [],
            "validation": {"is_valid": False, "errors": [str(exc)]},
            "line_items": [],
            "total_low": 0.0,
            "total_high": 0.0,
            "currency_system": {
                "base_currency": CURRENCY,
                "supported_currencies": [CURRENCY],
                "conversion_rates": {CURRENCY: 1.0},
            },
            "pricing_config": {"material_multipliers": {}, "style_multipliers": {}, "quality_multipliers": {}},
            "catalog": build_catalog_metadata(graph_data),
            "fallback": {
                "enabled": True,
                "triggered": False,
                "default_cost_per_sqft": float(DEFAULT_COST_PER_SQFT_FALLBACK),
            },
            "fx_service": build_fx_service(graph_data),
            "fx_fallback": build_fx_fallback(graph_data),
            "scenario_engine": build_scenario_engine(graph_data),
            "history_storage": build_history_storage(graph_data),
            "pricing_control": build_pricing_control(graph_data),
            "audit": {"enabled": True, "logs": [], "entries": []},
            "api": {"version": "v2", "backward_compatible": True},
            "precision": PRECISION_POLICY,
            "history": [],
            "scenarios": [],
            "suggestions": [],
        }


def _compute_estimate(graph_data: dict) -> dict:
    pricing_config = load_pricing_config(graph_data)
    pricing_control = build_pricing_control(graph_data)
    pricing_context = build_pricing_context(graph_data, pricing_config)
    fx_service = build_fx_service(graph_data)
    fx_fallback = build_fx_fallback(graph_data)
    currency_system, fx_fallback = resolve_currency_system(graph_data, fx_service, fx_fallback)
    scenario_engine = build_scenario_engine(graph_data)
    history_storage = build_history_storage(graph_data)
    audit_config = build_audit_config(graph_data)
    area_summary = calculate_area_summary(graph_data)

    material_items, assumptions = calculate_material_items(graph_data)
    furniture_items = calculate_furniture_items(graph_data)

    priced_goods = apply_pricing_to_items(material_items + furniture_items, pricing_context, pricing_config)
    for item in priced_goods:
        logger.info("pricing_rule_applied: item=%s category=%s", item.item, item.category)
    goods_total = _subtotal(priced_goods)

    labor_items = calculate_labor_items(area_summary, goods_total, pricing_context["style_tier"])
    service_items = calculate_service_items(area_summary, pricing_context["style_tier"])
    priced_support = apply_pricing_to_items(labor_items + service_items, pricing_context, pricing_config)
    for item in priced_support:
        logger.info("pricing_rule_applied: item=%s category=%s", item.item, item.category)
    support_total = _subtotal(priced_support)

    misc_items = calculate_misc_items(goods_total + support_total, pricing_context["style_tier"])
    priced_misc = apply_pricing_to_items(misc_items, pricing_context, pricing_config)
    for item in priced_misc:
        logger.info("pricing_rule_applied: item=%s category=%s", item.item, item.category)

    priced_items = priced_goods + priced_support + priced_misc
    fallback_state, fallback_assumptions, fallback_items = _apply_fallback_if_needed(
        graph_data=graph_data,
        area_summary=area_summary,
        existing_items=priced_items,
        pricing_context=pricing_context,
        pricing_config=pricing_config,
    )
    if fallback_items:
        priced_items.extend(fallback_items)
        assumptions.extend(fallback_assumptions)

    subtotal = _subtotal(priced_items)
    logger.info(
        "pricing_adjusted: city=%s price_index=%s market_variation=%s subtotal=%s",
        pricing_context["city"],
        pricing_context["price_index"],
        pricing_context["market_variation"],
        subtotal,
    )

    breakdown = build_breakdown(priced_items)
    logger.info("breakdown_computed: items=%d", len(breakdown))

    pricing_adjustments = build_pricing_adjustments(subtotal, pricing_context)
    estimate_sections = build_estimate_sections(priced_items)
    cost_per_sqft = _compute_cost_per_sqft(
        total_sqft=to_decimal(area_summary["total_sqft"]),
        final_total=to_decimal(pricing_adjustments["final_total"]),
    )
    legacy_line_items = build_legacy_line_items(priced_items, pricing_context["market_variation"])
    scenarios = generate_scenarios(
        pricing_adjustments["final_total"],
        graph_data,
        pricing_context,
        currency_system,
        scenario_engine,
    )

    validation_errors = validate_estimate_payload(
        priced_items=priced_items,
        breakdown=breakdown,
        subtotal=subtotal,
        pricing_config=pricing_config,
        pricing_context=pricing_context,
        pricing_adjustments=pricing_adjustments,
        currency_system=currency_system,
        fallback_state=fallback_state,
        final_cost_per_sqft=cost_per_sqft,
        confidence_weights=graph_data.get("confidence_weights", {}),
        fx_service=fx_service,
        fx_fallback=fx_fallback,
        scenarios=scenarios,
        pricing_control=pricing_control,
        audit_config=audit_config,
    )

    total_low = round(sum(item["total_low"] for item in legacy_line_items), 2)
    total_high = round(sum(item["total_high"] for item in legacy_line_items), 2)

    payload = {
        "status": "computed" if not validation_errors else "failed",
        "errors": validation_errors,
        "estimate_version": DEFAULT_ESTIMATE_VERSION,
        "currency": CURRENCY,
        "estimate": estimate_sections,
        "breakdown": breakdown,
        "area": {
            "total_sqft": area_summary["total_sqft"],
            "cost_per_sqft": float(cost_per_sqft),
        },
        "region": {
            "city": pricing_context["city"],
            "price_index": float(pricing_context["price_index"]),
        },
        "pricing_adjustments": pricing_adjustments,
        "confidence": build_confidence_score(
            graph_data=graph_data,
            area_summary=area_summary,
            validation_errors=validation_errors,
            fallback_triggered=fallback_state["triggered"],
            breakdown_count=len(breakdown),
            fx_fallback_used=fx_fallback["used"],
        ),
        "export": {
            "pdf_ready": True,
            "invoice_ready": True,
            "excel_ready": True,
            "erp_ready": True,
        },
        "assumptions": assumptions,
        "validation": {
            "is_valid": len(validation_errors) == 0,
            "errors": validation_errors,
        },
        "line_items": legacy_line_items,
        "total_low": total_low,
        "total_high": total_high,
        "pricing_config": serialize_pricing_config(pricing_config),
        "catalog": build_catalog_metadata(graph_data),
        "fallback": fallback_state,
        "fx_service": fx_service,
        "fx_fallback": fx_fallback,
        "scenario_engine": scenario_engine,
        "history_storage": history_storage,
        "pricing_control": pricing_control,
        "api": {"version": "v2", "backward_compatible": True},
        "precision": PRECISION_POLICY,
        "history": build_history_entries(graph_data, pricing_adjustments),
        "scenarios": scenarios,
    }

    payload = append_currency_conversions(payload, currency_system)
    payload["suggestions"] = build_cost_suggestions(payload, pricing_context)
    audit_entries = emit_audit_logs(audit_config, payload)
    payload["audit"] = {
        "enabled": audit_config["enabled"],
        "logs": audit_config["logs"],
        "entries": audit_entries,
    }
    for code in payload["currency_system"]["supported_currencies"]:
        logger.info("currency_converted: target_currency=%s final_total=%s", code, payload["converted_totals"][code]["final_total"])

    logger.info("estimate_finalized: status=%s final_total=%s", payload["status"], pricing_adjustments["final_total"])
    return payload


def _apply_fallback_if_needed(
    graph_data: dict,
    area_summary: dict,
    existing_items: list,
    pricing_context: dict,
    pricing_config: dict,
) -> tuple[dict, list[str], list]:
    fallback_config = graph_data.get("fallback", {})
    fallback_enabled = bool(fallback_config.get("enabled", True))
    default_cost_per_sqft = to_decimal(
        fallback_config.get("default_cost_per_sqft"),
        str(DEFAULT_COST_PER_SQFT_FALLBACK),
    )

    fallback_state = {
        "enabled": fallback_enabled,
        "triggered": False,
        "default_cost_per_sqft": float(default_cost_per_sqft),
    }
    assumptions: list[str] = []

    if not fallback_enabled:
        return fallback_state, assumptions, []

    has_catalog_gap = len(graph_data.get("materials", [])) == 0 or len(graph_data.get("objects", [])) == 0
    has_no_items = len(existing_items) == 0
    total_sqft = to_decimal(area_summary.get("total_sqft"))

    if not (has_catalog_gap or has_no_items) or total_sqft <= 0:
        return fallback_state, assumptions, []

    fallback_state["triggered"] = True
    logger.warning(
        "fallback_triggered: total_sqft=%s materials=%d objects=%d",
        total_sqft,
        len(graph_data.get("materials", [])),
        len(graph_data.get("objects", [])),
    )
    assumptions.append("Fallback pricing applied because catalog coverage was incomplete.")

    fallback_item = EstimateItem(
        item="Fallback baseline estimate",
        category="materials",
        subcategory="fallback",
        quantity=total_sqft,
        unit="sqft",
        base_unit_cost=default_cost_per_sqft,
        source="fallback",
    )

    priced_fallback = apply_pricing_to_items([fallback_item], pricing_context, pricing_config)
    return fallback_state, assumptions, priced_fallback


def _subtotal(items: list) -> Decimal:
    return round_money(sum((item.total_cost for item in items), Decimal("0")))


def _compute_cost_per_sqft(total_sqft: Decimal, final_total: Decimal) -> Decimal:
    if total_sqft <= 0:
        return Decimal("0.00")
    return round_money(final_total / total_sqft)
