"""Stage 4F — verify the 8 diagram-generation tools register correctly."""

from __future__ import annotations

import pytest


STAGE_4F_TOOLS = {
    "generate_concept_diagram",
    "generate_form_diagram",
    "generate_volumetric_diagram",
    "generate_volumetric_block_diagram",
    "generate_design_process_diagram",
    "generate_solid_void_diagram",
    "generate_spatial_organism_diagram",
    "generate_hierarchy_diagram",
}

# Each diagram tool has its own audit target so the project log
# distinguishes one diagram kind from another.
EXPECTED_AUDIT_TARGETS = {
    "generate_concept_diagram": "concept_diagram",
    "generate_form_diagram": "form_diagram",
    "generate_volumetric_diagram": "volumetric_diagram",
    "generate_volumetric_block_diagram": "volumetric_block_diagram",
    "generate_design_process_diagram": "design_process_diagram",
    "generate_solid_void_diagram": "solid_void_diagram",
    "generate_spatial_organism_diagram": "spatial_organism_diagram",
    "generate_hierarchy_diagram": "hierarchy_diagram",
}


@pytest.fixture(scope="module")
def registry():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return REGISTRY


def test_all_stage4f_tools_registered(registry):
    names = set(registry.names())
    missing = STAGE_4F_TOOLS - names
    assert not missing, f"Stage 4F tools missing: {missing}"


def test_total_tool_count_at_least_42(registry):
    """Stage 2 (1) + 4A (15) + 4B (8) + 4C (2) + 4D (3) + 4E (5) + 4F (8) = 42 minimum."""
    assert len(registry.names()) >= 42


def test_each_diagram_tool_requires_theme(registry):
    """Theme is required for every diagram — palette grounds every annotation."""
    for name in STAGE_4F_TOOLS:
        schema = registry.get(name).input_schema()
        props = schema.get("properties", {})
        required = set(schema.get("required", []))
        assert "theme" in props, f"{name}: missing theme prop"
        assert "theme" in required, f"{name}: theme not required"


def test_each_diagram_tool_has_canvas_dimension_caps(registry):
    """Canvas width/height must surface caps so the LLM can't request a 10000×10000 SVG."""
    for name in STAGE_4F_TOOLS:
        schema = registry.get(name).input_schema()
        props = schema.get("properties", {})
        for dim in ("canvas_width", "canvas_height"):
            assert dim in props, f"{name}: missing {dim}"
            assert "maximum" in props[dim], f"{name}: {dim} has no maximum"
            assert props[dim]["maximum"] <= 2400


def test_each_diagram_tool_has_audit_target(registry):
    for name, expected in EXPECTED_AUDIT_TARGETS.items():
        spec = registry.get(name)
        assert spec.audit_target_type == expected, (
            f"{name}: audit_target_type {spec.audit_target_type!r} != {expected!r}"
        )


def test_each_diagram_tool_has_generous_timeout(registry):
    """LLM JSON for diagrams + render is comparable to drawings; 90 s floor."""
    for name in STAGE_4F_TOOLS:
        spec = registry.get(name)
        assert spec.timeout_seconds >= 90.0, (
            f"{name}: timeout {spec.timeout_seconds}s < 90s"
        )


def test_every_stage4f_tool_has_substantive_description(registry):
    for name in STAGE_4F_TOOLS:
        spec = registry.get(name)
        assert spec.description, f"Tool {name!r} has empty description"
        assert len(spec.description) > 80, (
            f"Tool {name!r} description too short: {spec.description!r}"
        )


def test_all_42_plus_tools_in_definitions_for_llm(registry):
    defs = registry.definitions_for_llm()
    by_name = {d["name"]: d for d in defs}
    for name in STAGE_4F_TOOLS:
        assert name in by_name


def test_design_process_uniquely_accepts_architect_brief(registry):
    """Of the 8 diagrams, only design_process should accept architect_brief."""
    for name in STAGE_4F_TOOLS:
        schema = registry.get(name).input_schema()
        props = schema.get("properties", {})
        if name == "generate_design_process_diagram":
            assert "architect_brief" in props, "design_process must accept architect_brief"
        else:
            assert "architect_brief" not in props, (
                f"{name} should not accept architect_brief"
            )


def test_diagram_outputs_share_svg_and_spec_fields(registry):
    """All 8 tool output models must surface 'svg' + 'spec' (uniform DiagramOutput)."""
    for name in STAGE_4F_TOOLS:
        spec = registry.get(name)
        output_schema = spec.output_model.model_json_schema()
        props = output_schema.get("properties", {})
        assert "svg" in props, f"{name}: output missing 'svg'"
        assert "spec" in props, f"{name}: output missing 'spec'"
        assert "validation_passed" in props, f"{name}: output missing 'validation_passed'"


def test_each_diagram_tool_design_graph_optional(registry):
    """design_graph must be optional — diagrams can run from parametric_spec alone."""
    for name in STAGE_4F_TOOLS:
        schema = registry.get(name).input_schema()
        required = set(schema.get("required", []))
        assert "design_graph" not in required, (
            f"{name}: design_graph should be optional"
        )
