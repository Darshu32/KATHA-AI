"""Stage 4A — verify all 12 tools register correctly.

No DB calls; just tests that the @tool decorator wired everything up,
schemas are sensible, and the registry exposes them to the LLM.
"""

from __future__ import annotations

import pytest


# ─────────────────────────────────────────────────────────────────────
# All 12 expected tool names
# ─────────────────────────────────────────────────────────────────────


STAGE_4A_TOOLS = {
    # themes
    "lookup_theme",
    "list_themes",
    # clearances
    "check_door_width",
    "check_corridor_width",
    "check_room_area",
    # codes
    "check_room_against_nbc",
    "get_iecc_envelope",
    "lookup_climate_zone",
    "check_structural_span",
    # manufacturing
    "lookup_tolerance",
    "lookup_lead_time",
    "lookup_joinery",
    "list_qa_gates",
    # ergonomics
    "check_ergonomic_range",
    "lookup_ergonomic_envelope",
}


@pytest.fixture(scope="module")
def registry():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return REGISTRY


def test_all_stage4a_tools_registered(registry):
    names = set(registry.names())
    missing = STAGE_4A_TOOLS - names
    assert not missing, f"Stage 4A tools missing from registry: {missing}"


def test_estimate_project_cost_still_registered(registry):
    """Stage 2's tool must survive Stage 4A registration."""
    assert "estimate_project_cost" in registry.names()


def test_every_tool_has_description(registry):
    for name in STAGE_4A_TOOLS:
        spec = registry.get(name)
        assert spec.description, f"Tool {name!r} has empty description"
        # The LLM picks tools by description — must be substantive.
        assert len(spec.description) > 30, (
            f"Tool {name!r} has suspiciously short description: "
            f"{spec.description!r}"
        )


def test_every_tool_input_schema_is_valid(registry):
    """LLM-facing JSON schema must be well-formed."""
    for name in STAGE_4A_TOOLS:
        spec = registry.get(name)
        schema = spec.input_schema()
        assert schema["type"] == "object"
        assert "properties" in schema


def test_definitions_for_llm_includes_stage4a(registry):
    defs = registry.definitions_for_llm()
    by_name = {d["name"]: d for d in defs}
    for name in STAGE_4A_TOOLS:
        assert name in by_name
        d = by_name[name]
        assert {"name", "description", "input_schema"}.issubset(d.keys())


# ─────────────────────────────────────────────────────────────────────
# Per-tool input-schema sanity (each declares its required fields)
# ─────────────────────────────────────────────────────────────────────


def test_check_door_width_has_required_fields(registry):
    schema = registry.get("check_door_width").input_schema()
    props = schema.get("properties", {})
    assert {"door_type", "width_mm"}.issubset(props.keys())


def test_check_room_against_nbc_has_required_fields(registry):
    schema = registry.get("check_room_against_nbc").input_schema()
    props = schema.get("properties", {})
    assert {
        "room_type", "area_m2", "short_side_m", "height_m",
    }.issubset(props.keys())


def test_check_ergonomic_range_has_required_fields(registry):
    schema = registry.get("check_ergonomic_range").input_schema()
    props = schema.get("properties", {})
    assert {"item_group", "item", "dim", "value_mm"}.issubset(props.keys())


def test_lookup_climate_zone_accepts_zone(registry):
    schema = registry.get("lookup_climate_zone").input_schema()
    assert "zone" in schema.get("properties", {})


def test_list_qa_gates_takes_no_params(registry):
    """Empty input model — LLM should be able to call with {}."""
    schema = registry.get("list_qa_gates").input_schema()
    # Empty Pydantic model still has type=object, just no required props.
    assert schema["type"] == "object"
    required = schema.get("required", [])
    assert required == []
