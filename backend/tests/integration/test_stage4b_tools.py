"""Stage 4B integration tests — invoke each MEP tool against a real DB.

Requires Postgres + ``alembic upgrade head``. Skipped automatically
without ``KATHA_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def ctx(db_session):
    from app.agents.tool import ToolContext
    return ToolContext(session=db_session, actor_id=None, request_id="t4b")


async def _call(name: str, raw: dict, ctx) -> dict:
    from app.agents.tool import REGISTRY, call_tool
    from app.agents.tools import ensure_tools_registered

    ensure_tools_registered()
    return await call_tool(name, raw, ctx, registry=REGISTRY)


# ─────────────────────────────────────────────────────────────────────
# HVAC
# ─────────────────────────────────────────────────────────────────────


async def test_size_hvac_room_full_pipeline(ctx):
    """Bedroom 50 m³ × 18 m² → 100 CFM-ish + ~1.4 TR + 1.5 TR split."""
    result = await _call(
        "size_hvac_room",
        {
            "use_type": "bedroom",
            "room_volume_m3": 50.0,
            "floor_area_m2": 18.0,
        },
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["air_changes_per_hour"] == 2.0
    assert out["cfm_total"] is not None and out["cfm_total"] > 0
    assert out["tonnage"] is not None and out["tonnage"] > 1.0
    assert out["equipment"] is not None
    assert out["equipment"]["selected_tr"] >= out["tonnage"]
    assert out["capacity"] is not None
    assert out["capacity"]["btu_per_hr"] > 0


async def test_size_hvac_room_ventilation_only(ctx):
    """floor_area_m2 = 0 → only CFM is computed; tonnage skipped."""
    result = await _call(
        "size_hvac_room",
        {
            "use_type": "bathroom",
            "room_volume_m3": 12.0,
            "floor_area_m2": 0.0,
        },
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["cfm_total"] is not None
    assert out["tonnage"] is None
    assert out["equipment"] is None


async def test_size_hvac_room_unknown_use_type(ctx):
    """Bad use_type → notes recorded but tool still succeeds."""
    result = await _call(
        "size_hvac_room",
        {
            "use_type": "phantom_room",
            "room_volume_m3": 30.0,
            "floor_area_m2": 10.0,
        },
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["cfm_total"] is None
    assert out["notes"], "expected explanatory note for unknown use_type"


async def test_size_duct_picks_smallest_diameter(ctx):
    result = await _call("size_duct", {"cfm": 350.0}, ctx)
    assert result["ok"]
    # Legacy: 350 CFM → 300 mm.
    assert result["output"]["diameter_mm"] == 300


# ─────────────────────────────────────────────────────────────────────
# Electrical
# ─────────────────────────────────────────────────────────────────────


async def test_size_lighting_office_general(ctx):
    """20 m² office at 500 lux with 18W LED downlights."""
    result = await _call(
        "size_lighting",
        {
            "area_m2": 20.0,
            "lux_target": 500.0,
            "fixture_key": "led_downlight_18w",
            "use_type": "office_general",
        },
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["fixture_count"] is not None and out["fixture_count"] > 0
    assert out["watts_per_fixture"] == 18
    assert out["design_lux"] is not None and out["design_lux"] >= 500
    assert out["lighting_circuits"] >= 1


async def test_size_lighting_unknown_fixture(ctx):
    result = await _call(
        "size_lighting",
        {
            "area_m2": 20.0,
            "lux_target": 500.0,
            "fixture_key": "phantom_fixture",
        },
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["fixture_count"] is None
    assert out["notes"]
    # Circuits still computed (uses density lookup, not fixture).
    assert out["lighting_circuits"] >= 1


async def test_estimate_outlets_kitchen(ctx):
    result = await _call(
        "estimate_outlets",
        {"room_type": "kitchen", "perimeter_m": 14.0},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    # Kitchen rule: 0.45 outlets/m wall, min 6, task zones 4.
    assert out["general_outlets"] >= 6
    assert out["task_zones"] == 4


# ─────────────────────────────────────────────────────────────────────
# Plumbing
# ─────────────────────────────────────────────────────────────────────


async def test_summarize_water_supply_typical_2_bath_home(ctx):
    """Typical 2-bath home: 2 WC + 2 wash basins + 2 showers + 1 sink + 1 washer."""
    result = await _call(
        "summarize_water_supply",
        {
            "fixtures": [
                "water_closet", "water_closet",
                "wash_basin", "wash_basin",
                "shower", "shower",
                "kitchen_sink",
                "washing_machine",
            ],
        },
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    # Roll-up: 2.5+2.5 + 1.0+1.0 + 2.0+2.0 + 1.5 + 2.5 = 15.0 WSFU
    assert abs(out["wsfu_total"] - 15.0) < 0.1
    assert out["demand_gpm"] > 0
    assert out["supply_main_pipe_size_mm"] is not None


async def test_size_drain_pipe(ctx):
    result = await _call("size_drain_pipe", {"total_dfu": 20}, ctx)
    assert result["ok"]
    # Legacy: 20 DFU → 75 mm.
    assert result["output"]["pipe_size_mm"] == 75


async def test_size_vent_stack(ctx):
    result = await _call(
        "size_vent_stack",
        {"total_dfu": 15, "developed_length_m": 20.0},
        ctx,
    )
    assert result["ok"]
    # 15 DFU + 20 m → 50 mm at 60 m max.
    assert result["output"]["vent_size_mm"] == 50


# ─────────────────────────────────────────────────────────────────────
# MEP system cost
# ─────────────────────────────────────────────────────────────────────


async def test_mep_system_cost_estimate_residential_hvac(ctx):
    result = await _call(
        "mep_system_cost_estimate",
        {"system_key": "hvac_split_residential", "area_m2": 100.0},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["found"]
    # Legacy band: 1200 - 2200 INR/m².
    assert out["rate_inr_m2"]["low"] == 1200
    assert out["rate_inr_m2"]["high"] == 2200
    assert out["total_inr"]["low"] == 120000
    assert out["total_inr"]["high"] == 220000


async def test_mep_system_cost_estimate_unknown_system(ctx):
    result = await _call(
        "mep_system_cost_estimate",
        {"system_key": "phantom_system", "area_m2": 100.0},
        ctx,
    )
    assert result["ok"]
    out = result["output"]
    assert out["found"] is False
    assert out["note"] is not None


# ─────────────────────────────────────────────────────────────────────
# Validation envelope
# ─────────────────────────────────────────────────────────────────────


async def test_negative_area_rejected(ctx):
    result = await _call(
        "size_lighting",
        {"area_m2": -5.0, "lux_target": 500.0},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"


async def test_empty_fixtures_list_rejected(ctx):
    result = await _call(
        "summarize_water_supply",
        {"fixtures": []},
        ctx,
    )
    assert result["ok"] is False
    assert result["error"]["type"] == "validation_error"
