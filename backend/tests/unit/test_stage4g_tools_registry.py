"""Stage 4G — verify the 5 generation-pipeline tools register correctly."""

from __future__ import annotations

import pytest


STAGE_4G_TOOLS = {
    "generate_initial_design",
    "apply_theme",
    "edit_design_object",
    "list_design_versions",
    "validate_current_design",
}

WRITE_TOOLS = {
    "generate_initial_design": "design_graph",
    "apply_theme": "design_graph",
    "edit_design_object": "design_graph",
}

READ_TOOLS = {
    "list_design_versions",
    "validate_current_design",
}


@pytest.fixture(scope="module")
def registry():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return REGISTRY


def test_all_stage4g_tools_registered(registry):
    names = set(registry.names())
    missing = STAGE_4G_TOOLS - names
    assert not missing, f"Stage 4G tools missing: {missing}"


def test_total_tool_count_at_least_47(registry):
    """Stage 2 (1) + 4A (15) + 4B (8) + 4C (2) + 4D (3) + 4E (5) + 4F (8) + 4G (5) = 47."""
    assert len(registry.names()) >= 47


def test_write_tools_have_design_graph_audit_target(registry):
    """The 3 LLM-heavy generation tools must record an audit event so the
    project log has a complete trail of who changed the design when."""
    for name, expected in WRITE_TOOLS.items():
        spec = registry.get(name)
        assert spec.audit_target_type == expected, (
            f"{name}: audit_target_type {spec.audit_target_type!r} != {expected!r}"
        )


def test_read_tools_have_no_audit_target(registry):
    """Read tools must not write audit events (they don't change state)."""
    for name in READ_TOOLS:
        spec = registry.get(name)
        assert spec.audit_target_type is None, (
            f"{name}: read tool unexpectedly has audit_target_type "
            f"{spec.audit_target_type!r}"
        )


def test_write_tools_have_generous_timeouts(registry):
    """Initial generation can take a while; theme/edit are shorter."""
    initial = registry.get("generate_initial_design")
    assert initial.timeout_seconds >= 120.0, (
        f"generate_initial_design timeout {initial.timeout_seconds}s < 120s"
    )
    apply_theme = registry.get("apply_theme")
    assert apply_theme.timeout_seconds >= 90.0
    edit = registry.get("edit_design_object")
    assert edit.timeout_seconds >= 60.0


def test_generate_initial_design_requires_prompt(registry):
    schema = registry.get("generate_initial_design").input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert "prompt" in props
    assert "prompt" in required
    # min_length / max_length on the prompt protect against junk inputs.
    assert props["prompt"].get("minLength") == 10
    assert props["prompt"].get("maxLength") == 5000


def test_apply_theme_requires_new_style(registry):
    schema = registry.get("apply_theme").input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert "new_style" in props
    assert "new_style" in required
    # preserve_layout has a sensible default of True.
    assert props["preserve_layout"].get("default") is True


def test_edit_design_object_requires_object_id_and_prompt(registry):
    schema = registry.get("edit_design_object").input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert {"object_id", "edit_prompt"}.issubset(props.keys())
    assert {"object_id", "edit_prompt"}.issubset(required)


def test_list_design_versions_takes_no_required_input(registry):
    """Project-id comes from ctx, not input — schema should expose no required field."""
    schema = registry.get("list_design_versions").input_schema()
    required = set(schema.get("required", []))
    assert required == set(), (
        f"list_design_versions should have no required fields, got {required}"
    )


def test_validate_current_design_segment_default_residential(registry):
    schema = registry.get("validate_current_design").input_schema()
    props = schema.get("properties", {})
    assert "segment" in props
    assert props["segment"].get("default") == "residential"


def test_every_stage4g_tool_has_substantive_description(registry):
    for name in STAGE_4G_TOOLS:
        spec = registry.get(name)
        assert spec.description, f"Tool {name!r} has empty description"
        assert len(spec.description) > 80, (
            f"Tool {name!r} description too short: {spec.description!r}"
        )


def test_all_47_plus_tools_in_definitions_for_llm(registry):
    defs = registry.definitions_for_llm()
    by_name = {d["name"]: d for d in defs}
    for name in STAGE_4G_TOOLS:
        assert name in by_name


def test_generation_outputs_share_full_graph_data_field(registry):
    """All 3 write tools return GenerationOutput with full_graph_data preserved
    so the agent can chain drawing / diagram tools without a re-fetch."""
    for name in WRITE_TOOLS:
        spec = registry.get(name)
        output_schema = spec.output_model.model_json_schema()
        props = output_schema.get("properties", {})
        assert "full_graph_data" in props, f"{name}: output missing full_graph_data"
        assert "graph_summary" in props, f"{name}: output missing graph_summary"
        assert "version" in props
        assert "version_id" in props
