"""Modular estimation components."""

from app.services.estimation.audit import build_audit_config, emit_audit_logs
from app.services.estimation.breakdown import build_breakdown, build_legacy_line_items
from app.services.estimation.calculators import (
    calculate_area_summary,
    calculate_furniture_items,
    calculate_labor_items,
    calculate_material_items,
    calculate_misc_items,
    calculate_service_items,
)
from app.services.estimation.catalog_handler import build_catalog_metadata
from app.services.estimation.confidence import build_confidence_score
from app.services.estimation.currency import (
    append_currency_conversions,
    build_currency_system,
)
from app.services.estimation.fx_service import (
    build_fx_fallback,
    build_fx_service,
    resolve_currency_system,
)
from app.services.estimation.history_service import (
    build_history_entries,
    build_history_storage,
)
from app.services.estimation.history_repository import fetch_project_estimate_history
from app.services.estimation.pricing_control import build_pricing_control
from app.services.estimation.pricing_config import (
    load_pricing_config,
    serialize_pricing_config,
)
from app.services.estimation.pricing_rules import (
    apply_pricing_to_items,
    build_pricing_adjustments,
    build_pricing_context,
)
from app.services.estimation.scenario_engine import (
    build_scenario_engine,
    generate_scenarios,
)
from app.services.estimation.suggestions import build_cost_suggestions
from app.services.estimation.validation import validate_estimate_payload

__all__ = [
    "apply_pricing_to_items",
    "build_audit_config",
    "build_breakdown",
    "build_catalog_metadata",
    "build_confidence_score",
    "build_currency_system",
    "build_cost_suggestions",
    "build_fx_fallback",
    "build_fx_service",
    "build_history_entries",
    "build_history_storage",
    "build_legacy_line_items",
    "build_pricing_control",
    "build_pricing_adjustments",
    "build_pricing_context",
    "build_scenario_engine",
    "append_currency_conversions",
    "calculate_area_summary",
    "calculate_furniture_items",
    "calculate_labor_items",
    "calculate_material_items",
    "calculate_misc_items",
    "calculate_service_items",
    "emit_audit_logs",
    "fetch_project_estimate_history",
    "generate_scenarios",
    "load_pricing_config",
    "resolve_currency_system",
    "serialize_pricing_config",
    "validate_estimate_payload",
]
