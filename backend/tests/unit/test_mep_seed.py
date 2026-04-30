"""Stage 3C MEP seed-extraction tests.

Verifies every legacy MEP dict / table maps onto a building_standards
row with the right shape.
"""

from __future__ import annotations

import pytest

from app.knowledge import mep as mep_kb


@pytest.fixture(scope="module")
def seed():
    from app.services.standards.mep_seed import build_mep_seed_rows
    return build_mep_seed_rows()


# ─────────────────────────────────────────────────────────────────────
# Row hygiene
# ─────────────────────────────────────────────────────────────────────


def test_every_row_has_mep_category(seed):
    for row in seed:
        assert row["category"] == "mep"
        assert row["jurisdiction"] == "india_nbc"
        assert row["subcategory"] in {"hvac", "electrical", "plumbing", "system_cost"}
        assert row["source"].startswith("seed:mep")


def test_every_row_has_required_fields(seed):
    for row in seed:
        for key in ("id", "slug", "category", "subcategory",
                    "display_name", "data", "source", "source_doc"):
            assert key in row, f"row missing {key!r}"


# ─────────────────────────────────────────────────────────────────────
# HVAC coverage
# ─────────────────────────────────────────────────────────────────────


def test_every_ach_room_seeded(seed):
    slugs = {r["slug"] for r in seed if r["subcategory"] == "hvac"}
    for room in mep_kb.AIR_CHANGES_PER_HOUR.keys():
        assert f"mep_hvac_ach_{room}" in slugs


def test_ach_data_matches_legacy(seed):
    by_slug = {r["slug"]: r for r in seed}
    for room, value in mep_kb.AIR_CHANGES_PER_HOUR.items():
        row = by_slug[f"mep_hvac_ach_{room}"]
        assert row["data"]["air_changes_per_hour"] == float(value)


def test_equipment_band_table_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mep_hvac_equipment_bands"), None
    )
    assert row is not None
    assert row["data"]["entries"], "equipment band entries empty"
    assert len(row["data"]["entries"]) == len(mep_kb.EQUIPMENT_BAND_TR)


def test_duct_round_table_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mep_hvac_duct_round_diameter_table"),
        None,
    )
    assert row is not None
    assert len(row["data"]["entries"]) == len(mep_kb.DUCT_ROUND_DIAMETER_MM_BY_CFM)


# ─────────────────────────────────────────────────────────────────────
# Electrical coverage
# ─────────────────────────────────────────────────────────────────────


def test_every_lux_level_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for area in mep_kb.LUX_LEVELS.keys():
        assert f"mep_elec_lux_{area}" in slugs


def test_every_fixture_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for key in mep_kb.FIXTURE_CATALOGUE.keys():
        assert f"mep_elec_fixture_{key}" in slugs


def test_every_outlet_rule_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for room in mep_kb.OUTLET_COUNT_RULE.keys():
        assert f"mep_elec_outlet_rule_{room}" in slugs


def test_every_task_lighting_recipe_seeded(seed):
    by_slug = {r["slug"]: r for r in seed}
    for room, zones in mep_kb.TASK_LIGHTING_RECIPE.items():
        slug = f"mep_elec_task_lighting_{room}"
        assert slug in by_slug
        assert len(by_slug[slug]["data"]["zones"]) == len(zones)


def test_layout_rules_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mep_elec_layout_rules"), None
    )
    assert row is not None
    assert row["data"] == mep_kb.LIGHTING_LAYOUT_RULES


# ─────────────────────────────────────────────────────────────────────
# Plumbing coverage
# ─────────────────────────────────────────────────────────────────────


def test_every_dfu_fixture_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for fixture in mep_kb.DFU_PER_FIXTURE.keys():
        assert f"mep_plumb_dfu_{fixture}" in slugs


def test_every_wsfu_fixture_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for fixture in mep_kb.WSFU_PER_FIXTURE.keys():
        assert f"mep_plumb_wsfu_{fixture}" in slugs


def test_pipe_by_dfu_table_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mep_plumb_pipe_by_dfu_table"), None
    )
    assert row is not None
    assert len(row["data"]["entries"]) == len(mep_kb.PIPE_SIZE_MM_BY_DFU)


def test_hunters_curve_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mep_plumb_hunters_curve_flush_tank"),
        None,
    )
    assert row is not None
    assert len(row["data"]["entries"]) == len(mep_kb.HUNTERS_CURVE_FLUSH_TANK)


def test_vent_table_seeded(seed):
    row = next(
        (r for r in seed if r["slug"] == "mep_plumb_vent_stack_size_table"), None
    )
    assert row is not None
    assert len(row["data"]["entries"]) == len(mep_kb.VENT_STACK_SIZE_BY_DFU)


# ─────────────────────────────────────────────────────────────────────
# System cost coverage
# ─────────────────────────────────────────────────────────────────────


def test_every_system_cost_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for system_key in mep_kb.SYSTEM_COST_INR_PER_M2.keys():
        assert f"mep_system_cost_{system_key}" in slugs


def test_system_cost_band_matches_legacy(seed):
    by_slug = {r["slug"]: r for r in seed}
    for system_key, spec in mep_kb.SYSTEM_COST_INR_PER_M2.items():
        row = by_slug[f"mep_system_cost_{system_key}"]
        lo, hi = spec["range"]
        assert row["data"]["rate_inr_per_m2_low"] == float(lo)
        assert row["data"]["rate_inr_per_m2_high"] == float(hi)


# ─────────────────────────────────────────────────────────────────────
# Subcategory totals (regression check)
# ─────────────────────────────────────────────────────────────────────


def test_subcategory_row_counts_reasonable(seed):
    counts: dict[str, int] = {}
    for row in seed:
        counts[row["subcategory"]] = counts.get(row["subcategory"], 0) + 1
    assert counts.get("hvac", 0) >= 30  # ACH + CFM + cooling + duct + reg + tables
    assert counts.get("electrical", 0) >= 30  # lux + circuit + density + cat + rules
    assert counts.get("plumbing", 0) >= 25
    assert counts.get("system_cost", 0) == len(mep_kb.SYSTEM_COST_INR_PER_M2)
