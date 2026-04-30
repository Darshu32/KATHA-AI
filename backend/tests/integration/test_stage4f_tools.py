"""Stage 4F integration tests — orchestration of the 8 diagram generators.

Like Stage 4E, the underlying diagram services each make a live LLM
call **and** an in-process SVG render. The tests **monkeypatch** each
generator with a deterministic fake that returns the canonical
service shape.

Coverage strategy:

- One full happy-path test per tool, exercising the wiring (request
  fields → service request → result shape → DiagramOutput) end-to-end.
- One service-error test per tool, verifying ToolError envelope.
- Cross-cutting tests for: validation-failure surfacing, the
  design_process-only ``architect_brief`` parameter, and the uniform
  output shape across all 8 tools.

A separate ``KATHA_LLM_INTEGRATION_TESTS`` knob would pull in the
live services — out of scope for Stage 4F.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Fixtures + helpers
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
async def ctx(db_session):
    from app.agents.tool import ToolContext
    return ToolContext(session=db_session, actor_id=None, request_id="t4f")


async def _call(name: str, raw: dict, ctx) -> dict:
    from app.agents.tool import REGISTRY, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return await call_tool(name, raw, ctx, registry=REGISTRY)


def _fake_diagram_factory(
    spec_key: str,
    diagram_id: str,
    diagram_name: str,
    *,
    extra_meta: dict | None = None,
    validation: dict | None = None,
    svg: str = "<svg/>",
):
    """Build a fake diagram-generator returning the canonical service shape.

    Some services do *not* emit a ``validation`` block (e.g. concept).
    The fake lets the caller pass ``validation=None`` to mirror that.
    """

    async def fake(req):
        out = {
            "id": diagram_id,
            "name": diagram_name,
            "format": "svg",
            "model": "fake",
            "theme": getattr(req, "theme", "modern"),
            "knowledge": {"theme_rule_pack": {"display_name": "Stub"}},
            spec_key: {"narrative": "stub", "rationale": "stub"},
            "svg": svg,
            "meta": {"annotated": True, **(extra_meta or {})},
        }
        if validation is not None:
            out["validation"] = validation
        return out
    return fake


# Map: tool_name → (service_module_alias, spec_key, default_id, default_name).
# The "service_module_alias" is the dotted path inside the diagrams
# module to monkeypatch.
TOOL_MAP = {
    "generate_concept_diagram": (
        "app.agents.tools.diagrams._generate_concept_diagram",
        "concept_spec",
        "concept_transparency",
        "Concept Transparency",
    ),
    "generate_form_diagram": (
        "app.agents.tools.diagrams._generate_form_diagram",
        "form_spec",
        "form_development",
        "Form Development",
    ),
    "generate_volumetric_diagram": (
        "app.agents.tools.diagrams._generate_volumetric_diagram",
        "volumetric_spec",
        "volumetric_hierarchy",
        "Volumetric Hierarchy",
    ),
    "generate_volumetric_block_diagram": (
        "app.agents.tools.diagrams._generate_volumetric_block_diagram",
        "volumetric_block_spec",
        "volumetric_block",
        "Volumetric Diagram",
    ),
    "generate_design_process_diagram": (
        "app.agents.tools.diagrams._generate_design_process_diagram",
        "design_process_spec",
        "design_process",
        "Design Process",
    ),
    "generate_solid_void_diagram": (
        "app.agents.tools.diagrams._generate_solid_void_diagram",
        "solid_void_spec",
        "solid_void",
        "Solid vs Void",
    ),
    "generate_spatial_organism_diagram": (
        "app.agents.tools.diagrams._generate_spatial_organism_diagram",
        "spatial_organism_spec",
        "spatial_organism",
        "Spatial Organism",
    ),
    "generate_hierarchy_diagram": (
        "app.agents.tools.diagrams._generate_hierarchy_diagram",
        "hierarchy_spec",
        "hierarchy",
        "Hierarchy",
    ),
}


# ─────────────────────────────────────────────────────────────────────
# Validation envelope
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool_name", sorted(TOOL_MAP.keys()))
async def test_each_diagram_rejects_missing_theme(tool_name, ctx):
    """Every diagram tool must reject input without a theme."""
    result = await _call(tool_name, {}, ctx)
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_concept_rejects_oversized_canvas(ctx):
    result = await _call(
        "generate_concept_diagram",
        {"theme": "modern", "canvas_width": 5000},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_design_process_rejects_short_theme(ctx):
    result = await _call(
        "generate_design_process_diagram",
        {"theme": "x"},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


# ─────────────────────────────────────────────────────────────────────
# Happy paths — one per diagram
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool_name", sorted(TOOL_MAP.keys()))
async def test_each_diagram_happy_path(tool_name, monkeypatch, ctx):
    """For each diagram tool, monkeypatch the underlying generator and
    confirm the wrapper returns a uniform DiagramOutput."""
    patch_path, spec_key, default_id, default_name = TOOL_MAP[tool_name]
    fake = _fake_diagram_factory(
        spec_key=spec_key,
        diagram_id=default_id,
        diagram_name=default_name,
        extra_meta={"render_kind": tool_name},
        svg=f"<svg id={default_id}/>",
    )
    monkeypatch.setattr(patch_path, fake)

    result = await _call(tool_name, {"theme": "modern"}, ctx)
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["id"] == default_id
    assert out["name"] == default_name
    assert out["format"] == "svg"
    assert out["theme"] == "modern"
    assert out["validation_passed"] is True  # no validation block → True
    assert out["validation_failures"] == []
    assert out["svg"] == f"<svg id={default_id}/>"
    assert "narrative" in out["spec"]
    assert out["meta"]["render_kind"] == tool_name


# ─────────────────────────────────────────────────────────────────────
# Service-error → ToolError translation — one per diagram
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("tool_name", sorted(TOOL_MAP.keys()))
async def test_each_diagram_unknown_theme_surfaces_as_tool_error(
    tool_name, monkeypatch, ctx,
):
    """For each tool, when the underlying service raises its own *Error,
    the tool must translate it to a structured error envelope."""
    patch_path, _spec_key, _default_id, _default_name = TOOL_MAP[tool_name]

    # Pull the matching error class from the service module.
    service_error_lookup = {
        "generate_concept_diagram":
            "app.services.concept_diagram_service.ConceptDiagramError",
        "generate_form_diagram":
            "app.services.form_diagram_service.FormDiagramError",
        "generate_volumetric_diagram":
            "app.services.volumetric_diagram_service.VolumetricDiagramError",
        "generate_volumetric_block_diagram":
            "app.services.volumetric_block_diagram_service.VolumetricBlockError",
        "generate_design_process_diagram":
            "app.services.design_process_diagram_service.DesignProcessError",
        "generate_solid_void_diagram":
            "app.services.solid_void_diagram_service.SolidVoidError",
        "generate_spatial_organism_diagram":
            "app.services.spatial_organism_diagram_service.SpatialOrganismError",
        "generate_hierarchy_diagram":
            "app.services.hierarchy_diagram_service.HierarchyError",
    }
    err_path = service_error_lookup[tool_name]
    err_module, err_class = err_path.rsplit(".", 1)
    import importlib
    mod = importlib.import_module(err_module)
    err_cls = getattr(mod, err_class)

    async def fake(req):
        raise err_cls(f"Unknown theme '{req.theme}'.")

    monkeypatch.setattr(patch_path, fake)

    result = await _call(tool_name, {"theme": "phantom_theme"}, ctx)
    assert result["ok"] is False
    assert "phantom_theme" in result["error"]["message"]


# ─────────────────────────────────────────────────────────────────────
# Validation passthrough
# ─────────────────────────────────────────────────────────────────────


async def test_form_diagram_surfaces_validation_failures(monkeypatch, ctx):
    """The form service emits a validation block — we must propagate
    False flags into validation_failures (and skip non-bool entries)."""
    fake = _fake_diagram_factory(
        spec_key="form_spec",
        diagram_id="form_development",
        diagram_name="Form Development",
        validation={
            "grid_in_catalogue": False,
            "grid_key": "phantom_grid",  # non-bool, must be skipped
        },
    )
    monkeypatch.setattr(
        "app.agents.tools.diagrams._generate_form_diagram",
        fake,
    )

    result = await _call(
        "generate_form_diagram",
        {"theme": "modern"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["validation_passed"] is False
    assert out["validation_failures"] == ["grid_in_catalogue"]


async def test_hierarchy_diagram_surfaces_multiple_failures(monkeypatch, ctx):
    fake = _fake_diagram_factory(
        spec_key="hierarchy_spec",
        diagram_id="hierarchy",
        diagram_name="Hierarchy",
        validation={
            "visual_tiers_valid": True,
            "material_tiers_valid": False,
            "functional_tiers_valid": False,
            "bad_material_tiers": ["accent"],   # non-bool, skipped
            "bad_functional_tiers": ["other"],  # non-bool, skipped
        },
    )
    monkeypatch.setattr(
        "app.agents.tools.diagrams._generate_hierarchy_diagram",
        fake,
    )

    result = await _call(
        "generate_hierarchy_diagram",
        {"theme": "luxe"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["validation_passed"] is False
    assert set(out["validation_failures"]) == {
        "material_tiers_valid", "functional_tiers_valid",
    }


# ─────────────────────────────────────────────────────────────────────
# Design-process-only architect_brief
# ─────────────────────────────────────────────────────────────────────


async def test_design_process_passes_architect_brief_through(monkeypatch, ctx):
    captured = {}

    async def fake(req):
        captured["theme"] = req.theme
        captured["brief"] = req.architect_brief
        return {
            "id": "design_process",
            "name": "Design Process",
            "format": "svg",
            "theme": req.theme,
            "design_process_spec": {"steps": []},
            "svg": "<svg id=process/>",
            "meta": {"step_count": 0},
        }

    monkeypatch.setattr(
        "app.agents.tools.diagrams._generate_design_process_diagram",
        fake,
    )

    result = await _call(
        "generate_design_process_diagram",
        {
            "theme": "scandinavian",
            "architect_brief": {
                "client": "Test client",
                "constraints": ["budget", "lighting"],
            },
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    assert captured["theme"] == "scandinavian"
    assert captured["brief"]["client"] == "Test client"
    assert captured["brief"]["constraints"] == ["budget", "lighting"]


# ─────────────────────────────────────────────────────────────────────
# Empty validation block → passed
# ─────────────────────────────────────────────────────────────────────


async def test_concept_with_no_validation_block_passes(monkeypatch, ctx):
    """The concept service emits no ``validation`` block at all — the
    wrapper should treat that as validation_passed=True."""
    fake = _fake_diagram_factory(
        spec_key="concept_spec",
        diagram_id="concept_transparency",
        diagram_name="Concept Transparency",
        validation=None,  # explicitly omit
        extra_meta={"zone_count": 4, "emphasis_count": 2},
    )
    monkeypatch.setattr(
        "app.agents.tools.diagrams._generate_concept_diagram",
        fake,
    )

    result = await _call(
        "generate_concept_diagram",
        {"theme": "modern"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["validation_passed"] is True
    assert out["validation_failures"] == []
    assert out["meta"]["zone_count"] == 4
