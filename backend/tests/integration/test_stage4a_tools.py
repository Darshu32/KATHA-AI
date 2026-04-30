"""Stage 4A integration tests — invoke each tool against a real DB.

Requires Postgres + ``alembic upgrade head``. Skipped automatically
without ``KATHA_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture
async def ctx(db_session):
    from app.agents.tool import ToolContext
    return ToolContext(session=db_session, actor_id=None, request_id="t4a")


async def _call(name: str, raw: dict, ctx) -> dict:
    """Dispatch through the registry path the agent uses."""
    from app.agents.tool import REGISTRY, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return await call_tool(name, raw, ctx, registry=REGISTRY)


# ─────────────────────────────────────────────────────────────────────
# Themes
# ─────────────────────────────────────────────────────────────────────


async def test_lookup_theme_resolves_alias(ctx):
    result = await _call("lookup_theme", {"slug_or_alias": "mcm"}, ctx)
    assert result["ok"]
    out = result["output"]
    assert out["found"]
    assert out["rule_pack"]["display_name"] == "Mid-Century Modern"


async def test_list_themes_returns_5(ctx):
    result = await _call("list_themes", {}, ctx)
    assert result["ok"]
    out = result["output"]
    assert out["count"] >= 5
    slugs = {t["slug"] for t in out["themes"]}
    assert {"pedestal", "modern", "mid_century_modern"}.issubset(slugs)


# ─────────────────────────────────────────────────────────────────────
# Clearances
# ─────────────────────────────────────────────────────────────────────


async def test_check_door_width_warn_low(ctx):
    result = await _call(
        "check_door_width",
        {"door_type": "main_entry", "width_mm": 800},
        ctx,
    )
    assert result["ok"]
    assert result["output"]["status"] == "warn_low"
    assert result["output"]["source_section"] is not None


async def test_check_door_width_ok(ctx):
    result = await _call(
        "check_door_width",
        {"door_type": "main_entry", "width_mm": 1100},
        ctx,
    )
    assert result["ok"]
    assert result["output"]["status"] == "ok"


async def test_check_corridor_width(ctx):
    result = await _call(
        "check_corridor_width",
        {"segment": "residential", "width_mm": 750},
        ctx,
    )
    assert result["ok"]
    assert result["output"]["status"] == "warn_low"


async def test_check_room_area_warn_low(ctx):
    result = await _call(
        "check_room_area",
        {"room_type": "bedroom", "area_m2": 6.0, "segment": "residential"},
        ctx,
    )
    assert result["ok"]
    assert result["output"]["status"] == "warn_low"


# ─────────────────────────────────────────────────────────────────────
# Codes
# ─────────────────────────────────────────────────────────────────────


async def test_check_room_against_nbc_returns_issues(ctx):
    result = await _call(
        "check_room_against_nbc",
        {
            "room_type": "bedroom",
            "area_m2": 7.0,
            "short_side_m": 2.0,
            "height_m": 2.5,
        },
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["issue_count"] >= 1
    assert any("NBC" in i["code"] for i in out["issues"])


async def test_get_iecc_envelope(ctx):
    result = await _call(
        "get_iecc_envelope",
        {"climate_zone": "climate_zone_2_hot"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["found"]
    assert out["wall_u_value_w_m2k"] == 0.40


async def test_lookup_climate_zone_alias_tolerant(ctx):
    result = await _call(
        "lookup_climate_zone",
        {"zone": "Hot-Dry"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["found"]
    assert out["pack"]["display_name"] == "Hot & Dry"


async def test_check_structural_span_warn_high(ctx):
    result = await _call(
        "check_structural_span",
        {"material": "rcc_beam", "span_m": 12.0},
        ctx,
    )
    assert result["ok"]
    assert result["output"]["status"] == "warn_high"


# ─────────────────────────────────────────────────────────────────────
# Manufacturing
# ─────────────────────────────────────────────────────────────────────


async def test_lookup_tolerance(ctx):
    result = await _call(
        "lookup_tolerance",
        {"category": "structural"},
        ctx,
    )
    assert result["ok"]
    assert result["output"]["tolerance_plus_minus_mm"] == 1.0


async def test_lookup_lead_time(ctx):
    result = await _call(
        "lookup_lead_time",
        {"category": "metal_fabrication"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["found"]
    assert out["weeks_low"] == 6
    assert out["weeks_high"] == 10


async def test_lookup_joinery(ctx):
    result = await _call(
        "lookup_joinery",
        {"joinery_type": "mortise_tenon"},
        ctx,
    )
    assert result["ok"]
    spec = result["output"]["spec"]
    assert spec["strength"] == "very high"


async def test_list_qa_gates_returns_brd_canonical_order(ctx):
    result = await _call("list_qa_gates", {}, ctx)
    assert result["ok"]
    gates = result["output"]["gates"]
    assert len(gates) == 5
    stages = [g["stage"] for g in gates]
    assert stages == [
        "material_inspection",
        "dimension_verification",
        "finish_inspection",
        "assembly_check",
        "safety_testing",
    ]


# ─────────────────────────────────────────────────────────────────────
# Ergonomics
# ─────────────────────────────────────────────────────────────────────


async def test_check_ergonomic_range_warn_low(ctx):
    result = await _call(
        "check_ergonomic_range",
        {
            "item_group": "chair",
            "item": "dining_chair",
            "dim": "seat_height",
            "value_mm": 350,
        },
        ctx,
    )
    assert result["ok"]
    assert result["output"]["status"] == "warn_low"


async def test_lookup_ergonomic_envelope(ctx):
    result = await _call(
        "lookup_ergonomic_envelope",
        {"item_group": "chair", "item": "dining_chair"},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["found"]
    assert out["envelope"]["seat_height_mm"] == [400, 450]


# ─────────────────────────────────────────────────────────────────────
# Validation envelope (LLM-friendly errors)
# ─────────────────────────────────────────────────────────────────────


async def test_invalid_input_returns_validation_error_envelope(ctx):
    """Bad LLM input must NOT raise — must return ok:false+error."""
    result = await _call(
        "check_door_width",
        {"door_type": "main_entry", "width_mm": "not-a-number"},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_unknown_door_type_returns_unknown_status(ctx):
    """Tool succeeds but returns status='unknown' for unrecognised slug."""
    result = await _call(
        "check_door_width",
        {"door_type": "phantom_door", "width_mm": 900},
        ctx,
    )
    assert result["ok"]
    assert result["output"]["status"] == "unknown"
