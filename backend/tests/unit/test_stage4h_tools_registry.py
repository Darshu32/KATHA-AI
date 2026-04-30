"""Stage 4H — verify the 8 import / export tools register correctly."""

from __future__ import annotations

import pytest


STAGE_4H_TOOLS = {
    "list_export_formats",
    "list_import_formats",
    "list_export_recipients",
    "build_spec_bundle_for_current",
    "export_design_bundle",
    "parse_import_file",
    "generate_import_manifest",
    "generate_export_manifest",
}

# Write tools have audit targets; read / parse / discovery tools don't.
WRITE_AUDIT_TARGETS = {
    "export_design_bundle": "export_bundle",
    "generate_import_manifest": "import_manifest",
    "generate_export_manifest": "export_manifest",
}

NO_AUDIT_TOOLS = {
    "list_export_formats",
    "list_import_formats",
    "list_export_recipients",
    "build_spec_bundle_for_current",
    "parse_import_file",
}


@pytest.fixture(scope="module")
def registry():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return REGISTRY


def test_all_stage4h_tools_registered(registry):
    names = set(registry.names())
    missing = STAGE_4H_TOOLS - names
    assert not missing, f"Stage 4H tools missing: {missing}"


def test_total_tool_count_at_least_55(registry):
    """1 + 15 + 8 + 2 + 3 + 5 + 8 + 5 + 8 = 55."""
    assert len(registry.names()) >= 55


def test_write_tools_have_audit_target(registry):
    for name, expected in WRITE_AUDIT_TARGETS.items():
        spec = registry.get(name)
        assert spec.audit_target_type == expected, (
            f"{name}: audit_target_type {spec.audit_target_type!r} != {expected!r}"
        )


def test_read_tools_have_no_audit_target(registry):
    for name in NO_AUDIT_TOOLS:
        spec = registry.get(name)
        assert spec.audit_target_type is None, (
            f"{name}: read tool unexpectedly has audit_target_type "
            f"{spec.audit_target_type!r}"
        )


def test_export_design_bundle_requires_format_key(registry):
    schema = registry.get("export_design_bundle").input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert "format_key" in props
    assert "format_key" in required
    # Description should mention multiple format options for the LLM.
    desc = props["format_key"].get("description", "")
    assert "pdf" in desc.lower()
    assert "dxf" in desc.lower()


def test_parse_import_file_requires_filename_and_content(registry):
    schema = registry.get("parse_import_file").input_schema()
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    assert {"filename", "content_base64"}.issubset(props.keys())
    assert {"filename", "content_base64"}.issubset(required)


def test_generate_import_manifest_caps_imports_at_20(registry):
    schema = registry.get("generate_import_manifest").input_schema()
    props = schema.get("properties", {})
    assert "imports" in props
    assert props["imports"].get("maxItems") == 20
    assert props["imports"].get("minItems") == 1


def test_generate_export_manifest_caps_recipients_at_10(registry):
    schema = registry.get("generate_export_manifest").input_schema()
    props = schema.get("properties", {})
    assert "recipients" in props
    assert props["recipients"].get("maxItems") == 10


def test_discovery_tools_take_no_required_input(registry):
    """list_* / parse_* / build_* discovery tools must not require input
    fields the LLM doesn't have."""
    for name in (
        "list_export_formats",
        "list_import_formats",
        "list_export_recipients",
    ):
        schema = registry.get(name).input_schema()
        required = set(schema.get("required", []))
        assert required == set(), (
            f"{name}: should have no required fields, got {required}"
        )


def test_export_tools_have_appropriate_timeouts(registry):
    """LLM-heavy advisors get 90 s; export bundle gets 60 s; reads get 30 s."""
    assert registry.get("generate_import_manifest").timeout_seconds >= 60.0
    assert registry.get("generate_export_manifest").timeout_seconds >= 60.0
    assert registry.get("export_design_bundle").timeout_seconds >= 30.0
    for name in ("list_export_formats", "list_import_formats", "list_export_recipients"):
        # Reads should be quick.
        assert registry.get(name).timeout_seconds <= 60.0


def test_every_stage4h_tool_has_substantive_description(registry):
    for name in STAGE_4H_TOOLS:
        spec = registry.get(name)
        assert spec.description, f"Tool {name!r} has empty description"
        assert len(spec.description) > 80, (
            f"Tool {name!r} description too short: {spec.description!r}"
        )


def test_all_55_plus_tools_in_definitions_for_llm(registry):
    defs = registry.definitions_for_llm()
    by_name = {d["name"]: d for d in defs}
    for name in STAGE_4H_TOOLS:
        assert name in by_name


def test_export_design_bundle_output_has_inline_bytes_fields(registry):
    """The bytes-cap mechanism must surface in the output schema so the
    agent knows when to fall back to a side-channel download."""
    spec = registry.get("export_design_bundle")
    output_schema = spec.output_model.model_json_schema()
    props = output_schema.get("properties", {})
    for required in (
        "content_base64",
        "inline_bytes_omitted",
        "inline_bytes_limit",
        "size_bytes",
        "filename",
        "content_type",
    ):
        assert required in props, f"export_design_bundle output missing {required!r}"


def test_total_tool_count_matches_stage_4_target(registry):
    """End-of-Stage-4 target was ~50 tools. We should be at or above 55."""
    assert len(registry.names()) >= 55, (
        f"Expected at least 55 registered tools after Stage 4H, "
        f"got {len(registry.names())}"
    )
