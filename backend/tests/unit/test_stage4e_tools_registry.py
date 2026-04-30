"""Stage 4E — verify the 5 drawing-generation tools register correctly."""

from __future__ import annotations

import pytest


STAGE_4E_TOOLS = {
    "generate_plan_view_drawing",
    "generate_elevation_view_drawing",
    "generate_section_view_drawing",
    "generate_detail_sheet_drawing",
    "generate_isometric_view_drawing",
}

# Each drawing tool gets its own audit target — that's how the project
# log distinguishes one drawing kind from another.
EXPECTED_AUDIT_TARGETS = {
    "generate_plan_view_drawing": "plan_view_drawing",
    "generate_elevation_view_drawing": "elevation_view_drawing",
    "generate_section_view_drawing": "section_view_drawing",
    "generate_detail_sheet_drawing": "detail_sheet_drawing",
    "generate_isometric_view_drawing": "isometric_view_drawing",
}


@pytest.fixture(scope="module")
def registry():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return REGISTRY


def test_all_stage4e_tools_registered(registry):
    names = set(registry.names())
    missing = STAGE_4E_TOOLS - names
    assert not missing, f"Stage 4E tools missing: {missing}"


def test_total_tool_count_at_least_34(registry):
    """Stage 2 (1) + 4A (15) + 4B (8) + 4C (2) + 4D (3) + 4E (5) = 34 minimum."""
    assert len(registry.names()) >= 34


def test_each_drawing_tool_requires_theme(registry):
    """Theme is required for every drawing — palette grounds every line."""
    for name in STAGE_4E_TOOLS:
        schema = registry.get(name).input_schema()
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        assert "theme" in props, f"{name}: missing theme prop"
        assert "theme" in required, f"{name}: theme not required"


def test_each_drawing_tool_has_canvas_dimension_caps(registry):
    """Canvas width/height must surface caps so the LLM can't request a 10000×10000 SVG."""
    for name in STAGE_4E_TOOLS:
        schema = registry.get(name).input_schema()
        props = schema.get("properties", {})
        for dim in ("canvas_width", "canvas_height"):
            assert dim in props, f"{name}: missing {dim}"
            assert "maximum" in props[dim], f"{name}: {dim} has no maximum"
            assert props[dim]["maximum"] <= 2400


def test_each_drawing_tool_has_audit_target(registry):
    for name, expected in EXPECTED_AUDIT_TARGETS.items():
        spec = registry.get(name)
        assert spec.audit_target_type == expected, (
            f"{name}: audit_target_type {spec.audit_target_type!r} != {expected!r}"
        )


def test_each_drawing_tool_has_generous_timeout(registry):
    """LLM JSON for drawings is verbose; 120 s is the floor."""
    for name in STAGE_4E_TOOLS:
        spec = registry.get(name)
        assert spec.timeout_seconds >= 90.0, (
            f"{name}: timeout {spec.timeout_seconds}s < 90s"
        )


def test_every_stage4e_tool_has_substantive_description(registry):
    for name in STAGE_4E_TOOLS:
        spec = registry.get(name)
        assert spec.description, f"Tool {name!r} has empty description"
        assert len(spec.description) > 80, (
            f"Tool {name!r} description too short: {spec.description!r}"
        )


def test_all_34_plus_tools_in_definitions_for_llm(registry):
    defs = registry.definitions_for_llm()
    by_name = {d["name"]: d for d in defs}
    for name in STAGE_4E_TOOLS:
        assert name in by_name


def test_elevation_tool_exposes_piece_with_type_field(registry):
    """The shared ElevationPieceInput must surface a `type` slug for the LLM."""
    schema = registry.get("generate_elevation_view_drawing").input_schema()
    defs = schema.get("$defs") or schema.get("definitions") or {}
    # Find the nested piece schema in $defs.
    piece_schema = None
    for sub in defs.values():
        if isinstance(sub, dict) and "type" in (sub.get("properties") or {}) \
                and "material_hatch_key" in (sub.get("properties") or {}):
            piece_schema = sub
            break
    if piece_schema is None:
        # Inlined fallback.
        piece_schema = schema["properties"].get("piece") or {}
    assert "properties" in piece_schema
    assert "type" in piece_schema["properties"]


def test_isometric_tool_exposes_explode_enabled(registry):
    schema = registry.get("generate_isometric_view_drawing").input_schema()
    props = schema.get("properties", {})
    assert "explode_enabled" in props
    assert props["explode_enabled"].get("type") == "boolean"
    assert props["explode_enabled"].get("default") is False


def test_section_tool_exposes_view_target_default(registry):
    schema = registry.get("generate_section_view_drawing").input_schema()
    props = schema.get("properties", {})
    assert "view_target" in props
    assert props["view_target"].get("default") == "through_seat"


def test_drawing_outputs_share_svg_field(registry):
    """All 5 tool output models must surface an 'svg' string and a 'spec' dict."""
    for name in STAGE_4E_TOOLS:
        spec = registry.get(name)
        # Pull the output model's JSON schema directly from the spec.
        output_schema = spec.output_model.model_json_schema()
        props = output_schema.get("properties", {})
        assert "svg" in props, f"{name}: output missing 'svg'"
        assert "spec" in props, f"{name}: output missing 'spec'"
