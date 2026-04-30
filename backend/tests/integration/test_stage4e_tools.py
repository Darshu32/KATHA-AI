"""Stage 4E integration tests — orchestration of the 5 drawing generators.

The underlying drawing services each make a live LLM call **and** an
in-process SVG render. To keep CI hermetic + zero-cost, the tests
**monkeypatch** each generator with a deterministic fake that returns
the same shape the real services produce.

These exercise:

- Input-schema validation (theme required, canvas dim caps,
  short-theme rejection)
- Service-error → ToolError envelope translation
- Validation-failure surfacing (passed=False + list of failed flags)
- SVG passthrough (the rendered string lands intact in the output)
- Meta dict passthrough (per-drawing stat keys)
- ElevationPiece nested-input wiring (the elevation tool's `piece`
  reaches the underlying service's `piece`)

A separate ``KATHA_LLM_INTEGRATION_TESTS`` knob would pull in the
live services — out of scope for Stage 4E.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
async def ctx(db_session):
    from app.agents.tool import ToolContext
    return ToolContext(session=db_session, actor_id=None, request_id="t4e")


async def _call(name: str, raw: dict, ctx) -> dict:
    from app.agents.tool import REGISTRY, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return await call_tool(name, raw, ctx, registry=REGISTRY)


def _fake_drawing_factory(
    spec_key: str,
    drawing_id: str,
    drawing_name: str,
    *,
    extra_meta: dict | None = None,
    validation: dict | None = None,
    svg: str = "<svg/>",
):
    """Build a fake drawing-generator that returns the canonical shape."""

    async def fake(req):
        return {
            "id": drawing_id,
            "name": drawing_name,
            "format": "svg",
            "model": "fake",
            "theme": getattr(req, "theme", "modern"),
            "knowledge": {"theme_rule_pack": {"display_name": "Stub"}},
            spec_key: {"sheet_narrative": "stub", "scale": "1:50"},
            "svg": svg,
            "validation": validation or {"all_consistent": True},
            "meta": {"objects_drawn": 3, **(extra_meta or {})},
        }
    return fake


# ─────────────────────────────────────────────────────────────────────
# Validation envelope (no LLM needed)
# ─────────────────────────────────────────────────────────────────────


async def test_plan_view_rejects_missing_theme(ctx):
    result = await _call("generate_plan_view_drawing", {}, ctx)
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_elevation_view_rejects_short_theme(ctx):
    result = await _call(
        "generate_elevation_view_drawing",
        {"theme": "x"},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_section_view_rejects_oversized_canvas(ctx):
    """Canvas width capped at 2400 — a 5000-wide request must fail."""
    result = await _call(
        "generate_section_view_drawing",
        {"theme": "modern", "canvas_width": 5000},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_detail_sheet_rejects_undersized_canvas(ctx):
    """Canvas width floor at 480 — 100-wide request must fail."""
    result = await _call(
        "generate_detail_sheet_drawing",
        {"theme": "modern", "canvas_width": 100},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_isometric_view_rejects_missing_theme(ctx):
    result = await _call("generate_isometric_view_drawing", {}, ctx)
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


# ─────────────────────────────────────────────────────────────────────
# Plan view — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_plan_view_happy_path(monkeypatch, ctx):
    fake = _fake_drawing_factory(
        spec_key="plan_view_spec",
        drawing_id="plan_view",
        drawing_name="Plan View",
        extra_meta={"key_dimension_count": 4, "section_count": 1, "hatch_count": 2},
        svg="<svg id=plan/>",
    )
    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_plan_view_drawing",
        fake,
    )

    result = await _call(
        "generate_plan_view_drawing",
        {
            "theme": "mid_century_modern",
            "design_graph": {"objects": [{"type": "table"}], "room": {}},
            "sheet_title": "Living Room — Plan",
        },
        ctx,
    )

    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["id"] == "plan_view"
    assert out["theme"] == "mid_century_modern"
    assert out["validation_passed"] is True
    assert out["validation_failures"] == []
    assert out["svg"] == "<svg id=plan/>"
    assert out["spec"]["scale"] == "1:50"
    assert out["meta"]["key_dimension_count"] == 4
    assert out["format"] == "svg"


async def test_plan_view_unknown_theme_surfaces_as_tool_error(monkeypatch, ctx):
    from app.services.plan_view_drawing_service import PlanViewError

    async def fake(req):
        raise PlanViewError(f"Unknown theme '{req.theme}'.")

    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_plan_view_drawing",
        fake,
    )

    result = await _call(
        "generate_plan_view_drawing",
        {"theme": "phantom_theme"},
        ctx,
    )
    assert result["ok"] is False
    assert "phantom_theme" in result["error"]["message"]


async def test_plan_view_surfaces_validation_failures(monkeypatch, ctx):
    fake = _fake_drawing_factory(
        spec_key="plan_view_spec",
        drawing_id="plan_view",
        drawing_name="Plan View",
        validation={
            "scale_in_options": True,
            "hatch_keys_valid": False,
            "section_references_valid": False,
            "bad_section_references": [{"position": 1.4}],  # non-bool, ignored
        },
    )
    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_plan_view_drawing",
        fake,
    )

    result = await _call(
        "generate_plan_view_drawing",
        {"theme": "modern"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["validation_passed"] is False
    assert set(out["validation_failures"]) == {
        "hatch_keys_valid", "section_references_valid",
    }


# ─────────────────────────────────────────────────────────────────────
# Elevation view — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_elevation_view_passes_piece_through(monkeypatch, ctx):
    """Verify the nested ElevationPieceInput round-trips into the service request."""
    captured = {}

    async def fake(req):
        captured["theme"] = req.theme
        captured["piece_type"] = req.piece.type if req.piece else None
        captured["dims"] = req.piece.dimensions_mm if req.piece else None
        captured["view"] = req.view
        return {
            "id": "elevation_view",
            "name": "Elevation View",
            "format": "svg",
            "theme": req.theme,
            "elevation_view_spec": {"scale": "1:20"},
            "svg": "<svg id=elev/>",
            "validation": {"layout_consistent": True},
            "meta": {"height_dim_specced": 3},
        }

    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_elevation_view_drawing",
        fake,
    )

    result = await _call(
        "generate_elevation_view_drawing",
        {
            "theme": "scandinavian",
            "piece": {
                "type": "lounge_chair",
                "dimensions_mm": {"length": 700, "width": 800, "height": 850},
                "material_hatch_key": "wood_oak",
            },
            "view": "side",
        },
        ctx,
    )

    assert result["ok"], result.get("error")
    assert captured["theme"] == "scandinavian"
    assert captured["piece_type"] == "lounge_chair"
    assert captured["dims"]["height"] == 850
    assert captured["view"] == "side"
    out = result["output"]
    assert out["svg"] == "<svg id=elev/>"
    assert out["meta"]["height_dim_specced"] == 3


async def test_elevation_view_no_piece_required(monkeypatch, ctx):
    """If `piece` is omitted, the service still receives None and the
    tool accepts the input (the service falls back to design_graph)."""
    captured = {}

    async def fake(req):
        captured["piece_is_none"] = req.piece is None
        return {
            "id": "elevation_view",
            "name": "Elevation View",
            "format": "svg",
            "theme": req.theme,
            "elevation_view_spec": {},
            "svg": "<svg/>",
            "validation": {},
            "meta": {},
        }

    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_elevation_view_drawing",
        fake,
    )

    result = await _call(
        "generate_elevation_view_drawing",
        {
            "theme": "modern",
            "design_graph": {"objects": [], "room": {"length_m": 4}},
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    assert captured["piece_is_none"] is True


# ─────────────────────────────────────────────────────────────────────
# Section view — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_section_view_default_view_target(monkeypatch, ctx):
    """If the LLM omits `view_target`, the default `through_seat` reaches the service."""
    captured = {}

    async def fake(req):
        captured["view_target"] = req.view_target
        captured["cut_label"] = req.cut_label
        return {
            "id": "section_view",
            "name": "Section View",
            "format": "svg",
            "theme": req.theme,
            "section_view_spec": {"scale": "1:10"},
            "svg": "<svg id=sec/>",
            "validation": {"layer_stack_consistent": True},
            "meta": {"layer_count": 4},
        }

    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_section_view_drawing",
        fake,
    )

    result = await _call(
        "generate_section_view_drawing",
        {
            "theme": "industrial",
            "piece": {"type": "lounge_chair"},
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    assert captured["view_target"] == "through_seat"
    assert captured["cut_label"] == "A-A"


async def test_section_view_error_surfaces(monkeypatch, ctx):
    from app.services.section_view_drawing_service import SectionViewError

    async def fake(req):
        raise SectionViewError("LLM returned malformed JSON")

    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_section_view_drawing",
        fake,
    )

    result = await _call(
        "generate_section_view_drawing",
        {"theme": "modern", "piece": {"type": "dining_chair"}},
        ctx,
    )
    assert result["ok"] is False
    assert "malformed JSON" in result["error"]["message"]


# ─────────────────────────────────────────────────────────────────────
# Detail sheet — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_detail_sheet_passes_meta_through(monkeypatch, ctx):
    fake = _fake_drawing_factory(
        spec_key="detail_sheet_spec",
        drawing_id="detail_sheet",
        drawing_name="Detail Sheet",
        extra_meta={"cell_count": 6, "joint_cell_count": 2, "edge_cell_count": 1},
        svg="<svg id=detail/>",
    )
    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_detail_sheet_drawing",
        fake,
    )

    result = await _call(
        "generate_detail_sheet_drawing",
        {
            "theme": "luxe",
            "piece": {"type": "sideboard"},
            "sheet_title": "Sideboard — Details",
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["meta"]["cell_count"] == 6
    assert out["svg"] == "<svg id=detail/>"


# ─────────────────────────────────────────────────────────────────────
# Isometric view — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_isometric_view_explode_enabled_propagates(monkeypatch, ctx):
    captured = {}

    async def fake(req):
        captured["view_mode"] = req.view_mode
        captured["explode_enabled"] = req.explode_enabled
        return {
            "id": "isometric_view",
            "name": "Isometric View",
            "format": "svg",
            "theme": req.theme,
            "isometric_view_spec": {"scale": "1:20"},
            "svg": "<svg id=iso/>",
            "validation": {"projection_consistent": True},
            "meta": {"part_count": 8, "explode_used": req.explode_enabled},
        }

    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_isometric_view_drawing",
        fake,
    )

    result = await _call(
        "generate_isometric_view_drawing",
        {
            "theme": "modern",
            "piece": {"type": "wardrobe"},
            "view_mode": "perspective",
            "explode_enabled": True,
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    assert captured["view_mode"] == "perspective"
    assert captured["explode_enabled"] is True
    out = result["output"]
    assert out["meta"]["explode_used"] is True


async def test_isometric_view_default_view_mode(monkeypatch, ctx):
    captured = {}

    async def fake(req):
        captured["view_mode"] = req.view_mode
        captured["explode"] = req.explode_enabled
        return {
            "id": "isometric_view",
            "name": "Isometric View",
            "format": "svg",
            "theme": req.theme,
            "isometric_view_spec": {},
            "svg": "<svg/>",
            "validation": {},
            "meta": {},
        }

    monkeypatch.setattr(
        "app.agents.tools.drawings._generate_isometric_view_drawing",
        fake,
    )

    await _call(
        "generate_isometric_view_drawing",
        {"theme": "modern", "piece": {"type": "lounge_chair"}},
        ctx,
    )
    assert captured["view_mode"] == "iso"
    assert captured["explode"] is False
