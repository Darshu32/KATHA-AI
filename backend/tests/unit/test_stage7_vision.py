"""Stage 7 unit tests — vision prompts + stub provider + tool registry."""

from __future__ import annotations

import pytest

from app.vision import (
    StubVisionProvider,
    SUPPORTED_PURPOSES,
    VisionRequest,
    VisionImage,
    prompt_for_purpose,
)
from app.vision.anthropic_vision import _extract_json


# ─────────────────────────────────────────────────────────────────────
# prompt_for_purpose
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("purpose", list(SUPPORTED_PURPOSES))
def test_each_purpose_has_complete_spec(purpose):
    spec = prompt_for_purpose(purpose)
    assert spec.purpose == purpose
    assert spec.system_prompt
    assert spec.user_template
    schema = spec.output_schema
    assert schema["type"] == "object"
    assert "properties" in schema
    assert "required" in schema and schema["required"]


def test_prompt_focus_addendum_is_folded_into_user_message():
    spec = prompt_for_purpose("site_photo", focus="kitchen island geometry")
    assert "kitchen island geometry" in spec.user_template


def test_prompt_no_focus_leaves_user_template_clean():
    spec = prompt_for_purpose("reference")
    assert "Focus areas" not in spec.user_template


def test_prompt_unknown_purpose_raises_keyerror():
    with pytest.raises(KeyError):
        prompt_for_purpose("phantom_purpose")


def test_supported_purposes_covers_the_5_planned_kinds():
    assert set(SUPPORTED_PURPOSES) == {
        "site_photo",
        "reference",
        "mood_board",
        "hand_sketch",
        "existing_floor_plan",
    }


# ─────────────────────────────────────────────────────────────────────
# Stub provider
# ─────────────────────────────────────────────────────────────────────


async def test_stub_provider_returns_purpose_specific_fixture():
    provider = StubVisionProvider()
    spec = prompt_for_purpose("site_photo")
    request = VisionRequest(
        images=[VisionImage(data=b"\x00", mime_type="image/png", label="test")],
        system_prompt=spec.system_prompt,
        user_message=spec.user_template,
        output_schema=spec.output_schema,
        purpose="site_photo",
    )
    result = await provider.analyze(request)
    assert result.provider_name == "stub_vision"
    parsed = result.parsed
    # Site-photo fixture has these anchors.
    assert "summary" in parsed
    assert "orientation" in parsed
    assert "surroundings" in parsed


async def test_stub_provider_rejects_empty_images():
    provider = StubVisionProvider()
    spec = prompt_for_purpose("reference")
    request = VisionRequest(
        images=[],
        system_prompt=spec.system_prompt,
        user_message=spec.user_template,
        output_schema=spec.output_schema,
        purpose="reference",
    )
    from app.vision.base import VisionError
    with pytest.raises(VisionError):
        await provider.analyze(request)


async def test_stub_provider_set_fixture_overrides_default():
    provider = StubVisionProvider()
    provider.set_fixture("reference", {"summary": "custom override"})
    spec = prompt_for_purpose("reference")
    request = VisionRequest(
        images=[VisionImage(data=b"\x00", mime_type="image/png")],
        system_prompt=spec.system_prompt,
        user_message=spec.user_template,
        output_schema=spec.output_schema,
        purpose="reference",
    )
    result = await provider.analyze(request)
    assert result.parsed == {"summary": "custom override"}


async def test_stub_provider_unknown_purpose_returns_safe_empty_shape():
    """A purpose with no fixture shouldn't crash — returns a minimal
    object so downstream parsers don't blow up."""
    provider = StubVisionProvider()
    request = VisionRequest(
        images=[VisionImage(data=b"\x00", mime_type="image/png")],
        system_prompt="x", user_message="y",
        output_schema={}, purpose="surprise",
    )
    result = await provider.analyze(request)
    assert "summary" in result.parsed


# ─────────────────────────────────────────────────────────────────────
# _extract_json (Anthropic provider helper)
# ─────────────────────────────────────────────────────────────────────


def test_extract_json_parses_clean_json():
    out = _extract_json('{"summary": "hi", "n": 1}')
    assert out == {"summary": "hi", "n": 1}


def test_extract_json_strips_code_fences():
    text = '```json\n{"summary": "fenced"}\n```'
    out = _extract_json(text)
    assert out == {"summary": "fenced"}


def test_extract_json_finds_object_inside_chatty_reply():
    text = (
        "Here's the analysis:\n"
        '{"summary": "ok", "watch_outs": []}\n'
        "Hope that helps!"
    )
    out = _extract_json(text)
    assert out == {"summary": "ok", "watch_outs": []}


def test_extract_json_handles_nested_braces():
    text = '{"a": {"b": {"c": 1}}, "x": 2}'
    out = _extract_json(text)
    assert out == {"a": {"b": {"c": 1}}, "x": 2}


def test_extract_json_returns_none_on_garbage():
    assert _extract_json("not json at all") is None
    assert _extract_json("") is None


# ─────────────────────────────────────────────────────────────────────
# Tool registry shape
# ─────────────────────────────────────────────────────────────────────


_VISION_TOOLS = {
    "analyze_image",
    "analyze_site_photo",
    "extract_aesthetic",
    "sketch_to_floor_plan",
    "digitize_floor_plan",
}


def test_all_5_vision_tools_registered():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    names = set(REGISTRY.names())
    assert _VISION_TOOLS.issubset(names)


def test_vision_tools_are_read_only():
    """All vision tools should be read-only (no audit_target_type) so
    they're eligible for the Stage-5 parallel dispatcher."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    for name in _VISION_TOOLS:
        spec = REGISTRY.get(name)
        assert spec.audit_target_type is None, (
            f"{name}: vision tools should be read-only (no audit footprint), "
            f"got audit_target_type={spec.audit_target_type!r}"
        )


def test_analyze_image_requires_asset_id_and_purpose():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("analyze_image").input_schema()
    required = set(schema.get("required", []))
    assert {"asset_id", "purpose"}.issubset(required)


def test_extract_aesthetic_caps_at_8_assets():
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    schema = REGISTRY.get("extract_aesthetic").input_schema()
    props = schema["properties"]["asset_ids"]
    assert props.get("maxItems") == 8
    assert props.get("minItems") == 1


def test_total_tool_count_at_least_67_after_stage7():
    """Stage 6 (62) + Stage 7 (5) = 67."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    assert len(REGISTRY.names()) >= 67


def test_vision_tool_outputs_share_purpose_field():
    """All 5 tools return VisionAnalysisOutput which includes the
    purpose so the LLM can branch on it."""
    from app.agents.tool import REGISTRY
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    for name in _VISION_TOOLS:
        spec = REGISTRY.get(name)
        out_schema = spec.output_model.model_json_schema()
        props = out_schema.get("properties", {})
        assert "purpose" in props, f"{name}: output missing 'purpose'"
        assert "parsed" in props, f"{name}: output missing 'parsed'"
        assert "assets" in props, f"{name}: output missing 'assets'"
