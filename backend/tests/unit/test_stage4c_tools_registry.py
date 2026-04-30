"""Stage 4C — verify the 2 cost-extension tools register correctly."""

from __future__ import annotations

import pytest


STAGE_4C_TOOLS = {
    "compare_cost_scenarios",
    "cost_sensitivity",
}


@pytest.fixture(scope="module")
def registry():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return REGISTRY


def test_all_stage4c_tools_registered(registry):
    names = set(registry.names())
    missing = STAGE_4C_TOOLS - names
    assert not missing, f"Stage 4C tools missing: {missing}"


def test_total_tool_count_at_least_26(registry):
    """Stage 2 (1) + Stage 4A (15) + Stage 4B (8) + Stage 4C (2) = 26 minimum."""
    assert len(registry.names()) >= 26


def test_compare_cost_scenarios_schema_caps_at_4(registry):
    """The LLM must not be able to request more than 4 scenarios."""
    schema = registry.get("compare_cost_scenarios").input_schema()
    props = schema.get("properties", {})
    assert "scenarios" in props
    scenarios_prop = props["scenarios"]
    # Pydantic emits maxItems / minItems for list min_length / max_length.
    assert scenarios_prop.get("maxItems") == 4
    assert scenarios_prop.get("minItems") == 2


def test_cost_sensitivity_schema_caps_at_5(registry):
    schema = registry.get("cost_sensitivity").input_schema()
    props = schema.get("properties", {})
    assert "values" in props
    assert props["values"].get("maxItems") == 5
    assert props["values"].get("minItems") == 2
    assert "parameter" in props
    assert "base" in props


def test_compare_cost_scenarios_has_audit_target(registry):
    """Cost extensions write audit events (each call invokes the cost engine)."""
    spec = registry.get("compare_cost_scenarios")
    assert spec.audit_target_type == "cost_engine"


def test_cost_sensitivity_has_audit_target(registry):
    spec = registry.get("cost_sensitivity")
    assert spec.audit_target_type == "cost_engine"


def test_compare_cost_scenarios_timeout_generous(registry):
    """4 LLM calls in flight — needs more than the default 30s."""
    spec = registry.get("compare_cost_scenarios")
    assert spec.timeout_seconds >= 90.0


def test_cost_sensitivity_timeout_generous(registry):
    """5 variants + 1 base — needs more than the default 30s."""
    spec = registry.get("cost_sensitivity")
    assert spec.timeout_seconds >= 120.0


def test_every_stage4c_tool_has_substantive_description(registry):
    for name in STAGE_4C_TOOLS:
        spec = registry.get(name)
        assert spec.description, f"Tool {name!r} has empty description"
        assert len(spec.description) > 50, (
            f"Tool {name!r} description too short: {spec.description!r}"
        )


def test_all_26_plus_tools_in_definitions_for_llm(registry):
    defs = registry.definitions_for_llm()
    by_name = {d["name"]: d for d in defs}
    for name in STAGE_4C_TOOLS:
        assert name in by_name


def test_cost_sensitivity_parameter_enum_explained(registry):
    """The parameter description should enumerate allowed values so the
    LLM picks one without trial and error."""
    schema = registry.get("cost_sensitivity").input_schema()
    param_desc = schema["properties"]["parameter"].get("description", "")
    for axis in ("city", "complexity", "market_segment", "hardware_piece_count"):
        assert axis in param_desc, f"missing axis {axis!r} in parameter description"
