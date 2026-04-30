"""Stage 4D integration tests — orchestration of the 3 spec generators.

The underlying spec services (``generate_material_spec_sheet``,
``generate_manufacturing_spec``, ``generate_mep_spec``) make live LLM
calls. To keep CI hermetic + zero-cost, the tests **monkeypatch** each
generator with a deterministic fake that returns the same shape the
real services produce.

These exercise:

- Input-schema validation (theme required, room dimensions required)
- Service-error → ToolError envelope translation
- Validation-failure surfacing (passed=False + list of failed flags)
- Sections-authored discovery from the returned dict
- Full-spec passthrough so follow-up agent turns can drill in
- Audit trail (each successful call has audit_target_type set)

A separate ``KATHA_LLM_INTEGRATION_TESTS`` knob would pull in the
live services — out of scope for Stage 4D.
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
    return ToolContext(session=db_session, actor_id=None, request_id="t4d")


async def _call(name: str, raw: dict, ctx) -> dict:
    from app.agents.tool import REGISTRY, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return await call_tool(name, raw, ctx, registry=REGISTRY)


# ─────────────────────────────────────────────────────────────────────
# Validation envelope (no LLM needed)
# ─────────────────────────────────────────────────────────────────────


async def test_material_spec_rejects_missing_theme(ctx):
    result = await _call("generate_material_spec", {}, ctx)
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_manufacturing_spec_rejects_short_theme(ctx):
    """min_length=2 — a one-char theme fails validation."""
    result = await _call(
        "generate_manufacturing_spec",
        {"theme": "x"},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_mep_spec_rejects_missing_dimensions(ctx):
    result = await _call(
        "generate_mep_spec",
        {"room_use_type": "bedroom"},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_mep_spec_rejects_zero_dimension(ctx):
    """RoomDimensionsInput uses gt=0 — zero must fail."""
    result = await _call(
        "generate_mep_spec",
        {
            "room_use_type": "bedroom",
            "dimensions": {"length_m": 0.0, "width_m": 4.0, "height_m": 3.0},
        },
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_mep_spec_rejects_oversized_dimension(ctx):
    """height_m capped at 15."""
    result = await _call(
        "generate_mep_spec",
        {
            "room_use_type": "office_general",
            "dimensions": {"length_m": 5.0, "width_m": 4.0, "height_m": 25.0},
        },
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


# ─────────────────────────────────────────────────────────────────────
# generate_material_spec — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_material_spec_happy_path(monkeypatch, ctx):
    """Fake the LLM call; the tool should pass the request through and
    return a slim summary plus the full sheet."""

    async def fake(req):
        # Reflect a few request fields back so we can verify wiring.
        return {
            "id": "material_spec_sheet",
            "name": "Material Specification Sheet",
            "model": "fake",
            "theme": req.theme,
            "city": req.city or None,
            "knowledge": {"theme_rule_pack": {"display_name": req.theme.title()}},
            "material_spec_sheet": {
                "primary_structure": {"species": "walnut"},
                "secondary_materials": {},
                "hardware": {"metal": "brass"},
                "upholstery": {},
                "finishing": {"system": "wax_oil"},
                "cost_summary": {"total_inr": 150_000},
            },
            "validation": {
                "palette_consistent": True,
                "lead_time_in_band": True,
                "cost_in_band": True,
            },
        }

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_material_spec_sheet",
        fake,
    )

    result = await _call(
        "generate_material_spec",
        {
            "theme": "mid_century_modern",
            "project_name": "Test Project",
            "city": "bangalore",
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["id"] == "material_spec_sheet"
    assert out["theme"] == "mid_century_modern"
    assert out["validation_passed"] is True
    assert out["validation_failures"] == []
    # All 6 default sections should be in the authored list.
    assert {"primary_structure", "hardware", "cost_summary"}.issubset(
        out["sections_authored"]
    )
    # Full sheet preserved for follow-up turns.
    assert out["material_spec_sheet"]["primary_structure"]["species"] == "walnut"


async def test_material_spec_surfaces_validation_failures(monkeypatch, ctx):
    """A False boolean flag in validation must show up in
    ``validation_failures``; truthy and non-bool fields are ignored."""

    async def fake(req):
        return {
            "id": "material_spec_sheet",
            "name": "Material Specification Sheet",
            "theme": req.theme,
            "city": None,
            "material_spec_sheet": {"primary_structure": {}},
            "validation": {
                "palette_consistent": False,
                "lead_time_in_band": True,
                "cost_in_band": False,
                "palette_issues": ["walnut not in palette"],  # non-bool, ignored
            },
        }

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_material_spec_sheet",
        fake,
    )

    result = await _call(
        "generate_material_spec",
        {"theme": "modern"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["validation_passed"] is False
    assert set(out["validation_failures"]) == {"palette_consistent", "cost_in_band"}


async def test_material_spec_unknown_theme_surfaces_as_tool_error(monkeypatch, ctx):
    from app.services.material_spec_service import MaterialSpecError

    async def fake(req):
        raise MaterialSpecError("Unknown theme 'phantom'. No theme rule pack to ground the sheet.")

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_material_spec_sheet",
        fake,
    )

    result = await _call(
        "generate_material_spec",
        {"theme": "phantom_theme"},
        ctx,
    )
    assert result["ok"] is False
    assert "phantom" in result["error"]["message"]


# ─────────────────────────────────────────────────────────────────────
# generate_manufacturing_spec — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_manufacturing_spec_happy_path(monkeypatch, ctx):
    async def fake(req):
        return {
            "id": "manufacturing_spec",
            "name": "Manufacturing Specification",
            "theme": req.theme,
            "city": req.city or None,
            "knowledge": {"theme_rule_pack": {"display_name": "x"}},
            "manufacturing_spec": {
                "woodworking_notes": {"machine_precision_required": {"level": "structural"}},
                "metal_fabrication_notes": {},
                "upholstery_assembly_notes": {},
                "quality_assurance": {"qa_gates": ["material_inspection"]},
            },
            "validation": {"qa_gates_present": True, "tolerances_in_band": True},
        }

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_manufacturing_spec",
        fake,
    )

    result = await _call(
        "generate_manufacturing_spec",
        {
            "theme": "industrial",
            "city": "mumbai",
            "parametric_spec": {"wood_spec": {"primary_species": "teak"}},
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["validation_passed"] is True
    assert out["theme"] == "industrial"
    assert "woodworking_notes" in out["sections_authored"]
    assert out["manufacturing_spec"]["quality_assurance"]["qa_gates"] == ["material_inspection"]


async def test_manufacturing_spec_section_subset_passthrough(monkeypatch, ctx):
    """If the LLM caller restricts ``sections``, the tool propagates to the service request."""
    captured = {}

    async def fake(req):
        captured["sections"] = list(req.sections)
        return {
            "id": "manufacturing_spec",
            "name": "Manufacturing Specification",
            "theme": req.theme,
            "city": None,
            "manufacturing_spec": {"woodworking_notes": {}},
            "validation": {},
        }

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_manufacturing_spec",
        fake,
    )

    await _call(
        "generate_manufacturing_spec",
        {
            "theme": "scandinavian",
            "sections": ["woodworking_notes"],
        },
        ctx,
    )
    assert captured["sections"] == ["woodworking_notes"]


# ─────────────────────────────────────────────────────────────────────
# generate_mep_spec — orchestration
# ─────────────────────────────────────────────────────────────────────


async def test_mep_spec_happy_path(monkeypatch, ctx):
    captured = {}

    async def fake(req):
        captured["use"] = req.room_use_type
        captured["dims"] = (
            req.dimensions.length_m,
            req.dimensions.width_m,
            req.dimensions.height_m,
        )
        captured["fixtures"] = list(req.fixtures)
        return {
            "id": "mep_spec",
            "name": "MEP Specification",
            "room_use_type": req.room_use_type,
            "city": req.city or None,
            "knowledge": {},
            "mep_spec": {
                "hvac": {"cfm_total": 200, "tonnage": 1.5},
                "electrical": {"lighting_circuits": 1},
                "plumbing": {"drain_size_mm": 75},
                "cost": {"total_inr": 250_000},
            },
            "validation": {
                "cfm_within_range": True,
                "drain_size_in_scope": True,
            },
        }

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_mep_spec",
        fake,
    )

    result = await _call(
        "generate_mep_spec",
        {
            "room_use_type": "bedroom",
            "dimensions": {"length_m": 4.0, "width_m": 3.5, "height_m": 3.0},
            "occupancy": 2,
            "city": "bangalore",
            "fixtures": ["wash_basin"],
        },
        ctx,
    )
    assert result["ok"], result.get("error")
    out = result["output"]
    assert out["validation_passed"] is True
    assert out["room_use_type"] == "bedroom"
    assert out["mep_spec"]["hvac"]["tonnage"] == 1.5
    # Wiring sanity — request was constructed correctly.
    assert captured["use"] == "bedroom"
    assert captured["dims"] == (4.0, 3.5, 3.0)
    assert captured["fixtures"] == ["wash_basin"]


async def test_mep_spec_unknown_use_type_surfaces_as_tool_error(monkeypatch, ctx):
    from app.services.mep_spec_service import MEPSpecError

    async def fake(req):
        raise MEPSpecError(
            f"Unknown room_use_type '{req.room_use_type}'. Pick one of: ..."
        )

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_mep_spec",
        fake,
    )

    result = await _call(
        "generate_mep_spec",
        {
            "room_use_type": "phantom_room",
            "dimensions": {"length_m": 4.0, "width_m": 3.5, "height_m": 3.0},
        },
        ctx,
    )
    assert result["ok"] is False
    assert "Unknown room_use_type" in result["error"]["message"]


async def test_mep_spec_unknown_fixture_surfaces_as_tool_error(monkeypatch, ctx):
    from app.services.mep_spec_service import MEPSpecError

    async def fake(req):
        raise MEPSpecError(
            "Unknown plumbing fixture(s): phantom_drain. Pick from: ..."
        )

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_mep_spec",
        fake,
    )

    result = await _call(
        "generate_mep_spec",
        {
            "room_use_type": "bathroom",
            "dimensions": {"length_m": 2.0, "width_m": 2.5, "height_m": 3.0},
            "fixtures": ["phantom_drain"],
        },
        ctx,
    )
    assert result["ok"] is False
    assert "phantom_drain" in result["error"]["message"]


# ─────────────────────────────────────────────────────────────────────
# Defaults
# ─────────────────────────────────────────────────────────────────────


async def test_material_spec_default_sections_when_omitted(monkeypatch, ctx):
    captured = {}

    async def fake(req):
        captured["sections"] = list(req.sections)
        return {
            "id": "material_spec_sheet",
            "name": "Material Specification Sheet",
            "theme": req.theme,
            "city": None,
            "material_spec_sheet": {},
            "validation": {},
        }

    monkeypatch.setattr(
        "app.agents.tools.specs._generate_material_spec_sheet",
        fake,
    )

    await _call("generate_material_spec", {"theme": "modern"}, ctx)
    # All six BRD sections requested by default.
    assert set(captured["sections"]) == {
        "primary_structure", "secondary_materials", "hardware",
        "upholstery", "finishing", "cost_summary",
    }
