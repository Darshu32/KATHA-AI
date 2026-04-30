"""Integration tests for the Stage 3C MEP sizing helpers.

Requires Postgres + ``alembic upgrade head``. Skipped automatically
without ``KATHA_INTEGRATION_TESTS=1``.

Compares DB-backed helpers to the legacy sync helpers — values must
match exactly (modulo float rounding).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Seed presence
# ─────────────────────────────────────────────────────────────────────


async def test_mep_rows_present(db_session):
    from app.repositories.standards import StandardsRepository

    repo = StandardsRepository(db_session)
    rows = await repo.list_active(category="mep")
    assert len(rows) > 80, "expected ~90+ MEP rows after seed"
    subcats = {r["subcategory"] for r in rows}
    assert subcats == {"hvac", "electrical", "plumbing", "system_cost"}


# ─────────────────────────────────────────────────────────────────────
# HVAC parity with legacy
# ─────────────────────────────────────────────────────────────────────


async def test_hvac_cfm_matches_legacy(db_session):
    from app.knowledge import mep as legacy
    from app.services.standards import mep_sizing

    legacy_out = legacy.hvac_cfm(room_volume_m3=80, use_type="bedroom")
    db_out = await mep_sizing.hvac_cfm(
        db_session, room_volume_m3=80, use_type="bedroom"
    )
    assert legacy_out["ach"] == db_out["ach"]
    assert abs(legacy_out["cfm_total"] - db_out["cfm_total"]) < 0.5


async def test_cooling_tr_matches_legacy(db_session):
    from app.knowledge import mep as legacy
    from app.services.standards import mep_sizing

    legacy_out = legacy.cooling_tr(area_m2=120, use_type="office_general")
    db_out = await mep_sizing.cooling_tr(
        db_session, area_m2=120, use_type="office_general"
    )
    assert abs(legacy_out["tonnage"] - db_out["tonnage"]) < 0.05


async def test_equipment_shortlist_picks_smallest(db_session):
    from app.services.standards import mep_sizing

    result = await mep_sizing.equipment_shortlist(
        db_session, tonnage_required=1.3
    )
    # Legacy: 1.5 TR wall split is the smallest band ≥ 1.3 TR.
    assert result["selected_tr"] == 1.7
    assert "1.5 TR" in result["type"]


async def test_duct_round_diameter_picks_smallest(db_session):
    from app.services.standards import mep_sizing

    result = await mep_sizing.duct_round_diameter(db_session, cfm=350)
    # Legacy: 350 CFM → 300 mm.
    assert result["diameter_mm"] == 300


# ─────────────────────────────────────────────────────────────────────
# Electrical parity
# ─────────────────────────────────────────────────────────────────────


async def test_lighting_circuits_residential(db_session):
    from app.services.standards import mep_sizing

    out = await mep_sizing.lighting_circuits(
        db_session, area_m2=100, use="residential"
    )
    # 100 m² × 30 W/m² = 3000 W; max 1500 W per circuit → 3 circuits.
    assert out["density_w_m2"] == 30
    assert out["lighting_circuits"] == 3


async def test_ambient_fixture_count(db_session):
    from app.services.standards import mep_sizing

    out = await mep_sizing.ambient_fixture_count(
        db_session,
        area_m2=20,
        lux_target=300,
        fixture_key="led_downlight_18w",
    )
    # 18 W LED downlight at 1700 lm × 0.8 × 0.7 = 952 effective lumens.
    # Required: 300 × 20 = 6000; ceil(6000/952) = 7.
    assert out["count"] == 7


async def test_outlet_estimate_kitchen(db_session):
    from app.services.standards import mep_sizing

    out = await mep_sizing.outlet_estimate(
        db_session, room_type="kitchen", perimeter_m=12.0
    )
    # Kitchen rule: 0.45 outlets/m wall, min 6, task zones 4.
    # ceil(12 × 0.45) = 6, max(6, 6) = 6.
    assert out["general_outlets"] >= 6
    assert out["task_zones"] == 4


# ─────────────────────────────────────────────────────────────────────
# Plumbing parity
# ─────────────────────────────────────────────────────────────────────


async def test_pipe_size_for_dfu(db_session):
    from app.services.standards import mep_sizing

    out = await mep_sizing.pipe_size_for_dfu(db_session, total_dfu=20)
    # Legacy: 20 DFU → 75 mm pipe.
    assert out["pipe_size_mm"] == 75


async def test_water_supply_demand_gpm_zero_wsfu(db_session):
    from app.services.standards import mep_sizing

    out = await mep_sizing.water_supply_demand_gpm(db_session, total_wsfu=0)
    assert out["demand_gpm"] == 0.0


async def test_water_supply_demand_gpm_typical_home(db_session):
    from app.services.standards import mep_sizing

    # 2-bath home: 2× WC (5.0) + 2× wash basin (2.0) + 2× shower (4.0)
    #             + 1× kitchen sink (1.5) + 1× washing machine (2.5) = 15 WSFU
    out = await mep_sizing.water_supply_demand_gpm(db_session, total_wsfu=15)
    # Hunter's curve at 15 WSFU = 19.0 GPM.
    assert abs(out["demand_gpm"] - 19.0) < 0.1


async def test_vent_size_for_dfu(db_session):
    from app.services.standards import mep_sizing

    out = await mep_sizing.vent_size_for_dfu(
        db_session, total_dfu=15, developed_length_m=20
    )
    # Legacy: 15 DFU + 20 m → still fits 50 mm at 60 m max.
    assert out["vent_size_mm"] == 50


async def test_fixture_water_supply_summary(db_session):
    from app.services.standards import mep_sizing

    out = await mep_sizing.fixture_water_supply_summary(
        db_session,
        fixtures=["water_closet", "wash_basin", "shower", "kitchen_sink"],
    )
    # Roll-up: 2.5 + 1.0 + 2.0 + 1.5 = 7.0 WSFU.
    assert abs(out["wsfu_total"] - 7.0) < 0.1
    assert out["supply_main_pipe_size_mm"] is not None


# ─────────────────────────────────────────────────────────────────────
# System cost
# ─────────────────────────────────────────────────────────────────────


async def test_system_cost_estimate(db_session):
    from app.services.standards import mep_sizing

    out = await mep_sizing.system_cost_estimate(
        db_session, system_key="hvac_split_residential", area_m2=100
    )
    # Legacy band: 1200-2200 INR/m².
    assert out["rate_inr_m2"]["low"] == 1200
    assert out["rate_inr_m2"]["high"] == 2200
    assert out["total_inr"]["low"] == 120000
    assert out["total_inr"]["high"] == 220000


# ─────────────────────────────────────────────────────────────────────
# Versioning
# ─────────────────────────────────────────────────────────────────────


async def test_admin_update_propagates_to_sizing_helper(db_session):
    """Update bedroom ACH from 2.0 → 2.5; helper picks up new value."""
    from app.repositories.standards import StandardsRepository
    from app.services.standards import mep_sizing

    repo = StandardsRepository(db_session)

    # Sanity baseline.
    before = await mep_sizing.hvac_cfm(
        db_session, room_volume_m3=50, use_type="bedroom"
    )
    assert before["ach"] == 2.0

    await repo.update_data(
        slug="mep_hvac_ach_bedroom",
        category="mep",
        new_data={"room_type": "bedroom", "air_changes_per_hour": 2.5},
        actor_id=None,
        reason="integration test bump",
    )
    await db_session.flush()

    after = await mep_sizing.hvac_cfm(
        db_session, room_volume_m3=50, use_type="bedroom"
    )
    assert after["ach"] == 2.5
    assert after["cfm_total"] > before["cfm_total"]
