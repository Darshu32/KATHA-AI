"""Stage 4D — verify the 3 spec-generation tools register correctly."""

from __future__ import annotations

import pytest


STAGE_4D_TOOLS = {
    "generate_material_spec",
    "generate_manufacturing_spec",
    "generate_mep_spec",
}


@pytest.fixture(scope="module")
def registry():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return REGISTRY


def test_all_stage4d_tools_registered(registry):
    names = set(registry.names())
    missing = STAGE_4D_TOOLS - names
    assert not missing, f"Stage 4D tools missing: {missing}"


def test_total_tool_count_at_least_29(registry):
    """Stage 2 (1) + 4A (15) + 4B (8) + 4C (2) + 4D (3) = 29 minimum."""
    assert len(registry.names()) >= 29


def test_generate_material_spec_requires_theme(registry):
    schema = registry.get("generate_material_spec").input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert "theme" in props
    assert "theme" in required


def test_generate_manufacturing_spec_requires_theme(registry):
    schema = registry.get("generate_manufacturing_spec").input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert "theme" in props
    assert "theme" in required


def test_generate_mep_spec_requires_room_use_and_dimensions(registry):
    schema = registry.get("generate_mep_spec").input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert {"room_use_type", "dimensions"}.issubset(props.keys())
    assert {"room_use_type", "dimensions"}.issubset(required)


def test_mep_spec_dimensions_is_object_with_lwh(registry):
    """The nested RoomDimensions type must surface length/width/height."""
    schema = registry.get("generate_mep_spec").input_schema()
    # Pydantic v2 emits nested types as $ref into $defs.
    defs = schema.get("$defs") or schema.get("definitions") or {}
    # Either inlined or under $defs — find a sub-schema with the right props.
    nested = None
    for sub in defs.values():
        if isinstance(sub, dict) and {"length_m", "width_m", "height_m"}.issubset(
            (sub.get("properties") or {}).keys()
        ):
            nested = sub
            break
    if nested is None:
        # Fall back to inlined "dimensions" property.
        nested = schema["properties"]["dimensions"]
    assert {"length_m", "width_m", "height_m"}.issubset(
        (nested.get("properties") or {}).keys()
    ), "RoomDimensionsInput must expose length_m / width_m / height_m"


def test_each_spec_tool_has_audit_target(registry):
    """All three are write tools — every successful call writes an
    AuditEvent so the project log records who generated which spec."""
    targets = {
        "generate_material_spec": "material_spec_sheet",
        "generate_manufacturing_spec": "manufacturing_spec",
        "generate_mep_spec": "mep_spec",
    }
    for name, target in targets.items():
        spec = registry.get(name)
        assert spec.audit_target_type == target, (
            f"{name}: audit_target_type {spec.audit_target_type!r} != {target!r}"
        )


def test_each_spec_tool_has_generous_timeout(registry):
    """LLM round-trip is 30–45 s on average; allow ample headroom."""
    for name in STAGE_4D_TOOLS:
        spec = registry.get(name)
        assert spec.timeout_seconds >= 60.0, (
            f"{name}: timeout {spec.timeout_seconds}s < 60s"
        )


def test_every_stage4d_tool_has_substantive_description(registry):
    for name in STAGE_4D_TOOLS:
        spec = registry.get(name)
        assert spec.description, f"Tool {name!r} has empty description"
        assert len(spec.description) > 80, (
            f"Tool {name!r} description too short: {spec.description!r}"
        )


def test_all_29_plus_tools_in_definitions_for_llm(registry):
    defs = registry.definitions_for_llm()
    by_name = {d["name"]: d for d in defs}
    for name in STAGE_4D_TOOLS:
        assert name in by_name


def test_material_spec_sections_default_lists_all_six(registry):
    """If the LLM omits ``sections`` we should still author all 6 BRD sections."""
    schema = registry.get("generate_material_spec").input_schema()
    sections_prop = schema["properties"]["sections"]
    # Pydantic emits default values via "default".
    default = sections_prop.get("default")
    assert default is not None
    assert {
        "primary_structure", "secondary_materials", "hardware",
        "upholstery", "finishing", "cost_summary",
    } == set(default)
