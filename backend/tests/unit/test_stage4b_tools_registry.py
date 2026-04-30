"""Stage 4B — verify all 8 MEP tools register correctly."""

from __future__ import annotations

import pytest


STAGE_4B_TOOLS = {
    # HVAC
    "size_hvac_room",
    "size_duct",
    # Electrical
    "size_lighting",
    "estimate_outlets",
    # Plumbing
    "summarize_water_supply",
    "size_drain_pipe",
    "size_vent_stack",
    # System cost
    "mep_system_cost_estimate",
}


@pytest.fixture(scope="module")
def registry():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return REGISTRY


def test_all_stage4b_tools_registered(registry):
    names = set(registry.names())
    missing = STAGE_4B_TOOLS - names
    assert not missing, f"Stage 4B tools missing: {missing}"


def test_total_tool_count_at_least_24(registry):
    """Stage 2 (1) + Stage 4A (15) + Stage 4B (8) = 24 minimum."""
    assert len(registry.names()) >= 24


def test_size_hvac_room_schema_has_required_fields(registry):
    schema = registry.get("size_hvac_room").input_schema()
    props = schema.get("properties", {})
    assert {"use_type", "room_volume_m3", "floor_area_m2"}.issubset(props.keys())


def test_size_lighting_schema_has_required_fields(registry):
    schema = registry.get("size_lighting").input_schema()
    props = schema.get("properties", {})
    assert {"area_m2", "lux_target"}.issubset(props.keys())


def test_summarize_water_supply_takes_fixture_array(registry):
    schema = registry.get("summarize_water_supply").input_schema()
    props = schema.get("properties", {})
    assert "fixtures" in props
    assert props["fixtures"].get("type") == "array"


def test_mep_system_cost_estimate_schema(registry):
    schema = registry.get("mep_system_cost_estimate").input_schema()
    props = schema.get("properties", {})
    assert {"system_key", "area_m2"}.issubset(props.keys())


def test_every_stage4b_tool_has_substantive_description(registry):
    for name in STAGE_4B_TOOLS:
        spec = registry.get(name)
        assert spec.description, f"Tool {name!r} has empty description"
        assert len(spec.description) > 30, (
            f"Tool {name!r} description too short: {spec.description!r}"
        )


def test_all_24_plus_tools_in_definitions_for_llm(registry):
    defs = registry.definitions_for_llm()
    by_name = {d["name"]: d for d in defs}
    for name in STAGE_4B_TOOLS:
        assert name in by_name
