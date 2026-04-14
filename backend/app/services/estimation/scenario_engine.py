"""Dynamic scenario generation engine."""

from __future__ import annotations

import logging
from decimal import Decimal

from app.services.estimation.catalog import CURRENCY
from app.services.estimation.currency import convert_amount
from app.services.estimation.models import round_money, to_decimal

logger = logging.getLogger(__name__)


def build_scenario_engine(graph_data: dict) -> dict:
    config = graph_data.get("scenario_engine", {})
    return {
        "based_on": config.get("based_on", ["budget_constraints", "style", "quality"]),
        "auto_generate": bool(config.get("auto_generate", True)),
    }


def generate_scenarios(
    final_total: float,
    graph_data: dict,
    pricing_context: dict,
    currency_system: dict,
    scenario_engine: dict,
) -> list[dict]:
    if not scenario_engine["auto_generate"]:
        return []

    current_total = to_decimal(final_total)
    budget = _resolve_budget_multiplier(graph_data)
    style = _resolve_style_multiplier(pricing_context["style_tier"])
    quality = _resolve_quality_multiplier(pricing_context["default_quality"])

    scenario_map = {
        "budget": round_money(current_total * budget),
        "standard": round_money(current_total),
        "premium": round_money(current_total * style * quality),
    }

    scenarios = []
    for name, total in scenario_map.items():
        scenario = {
            "name": name,
            "total": float(total),
            "currency": CURRENCY,
            "converted_totals": {
                code: float(convert_amount(total, code, currency_system))
                for code in currency_system["supported_currencies"]
            },
        }
        scenarios.append(scenario)
        logger.info("scenario_generated: name=%s total=%s", name, total)

    return scenarios


def _resolve_budget_multiplier(graph_data: dict) -> Decimal:
    budget = graph_data.get("budget")
    if budget in (None, ""):
        return Decimal("0.85")
    return Decimal("0.80")


def _resolve_style_multiplier(style_tier: str) -> Decimal:
    if style_tier in {"premium", "luxury"}:
        return Decimal("1.12")
    return Decimal("1.05")


def _resolve_quality_multiplier(quality: str) -> Decimal:
    if quality == "premium":
        return Decimal("1.10")
    if quality == "luxury":
        return Decimal("1.18")
    return Decimal("1.06")
