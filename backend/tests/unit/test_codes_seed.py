"""Stage 3E codes seed-extraction tests."""

from __future__ import annotations

import pytest

from app.knowledge import climate as climate_kb
from app.knowledge import codes as codes_kb
from app.knowledge import ibc as ibc_kb
from app.knowledge import structural as structural_kb


@pytest.fixture(scope="module")
def seed():
    from app.services.standards.codes_seed import build_codes_seed_rows
    return build_codes_seed_rows()


# ─────────────────────────────────────────────────────────────────────
# Row hygiene
# ─────────────────────────────────────────────────────────────────────


def test_every_row_has_code_category(seed):
    for row in seed:
        assert row["category"] == "code"
        assert row["jurisdiction"] in {"india_nbc", "international_ibc"}
        assert row["source"].startswith("seed:")


def test_every_row_has_required_fields(seed):
    for row in seed:
        for key in (
            "id", "slug", "category", "subcategory", "jurisdiction",
            "display_name", "data", "source", "source_doc",
        ):
            assert key in row, f"row missing {key!r}"


# ─────────────────────────────────────────────────────────────────────
# NBC India
# ─────────────────────────────────────────────────────────────────────


def test_every_nbc_rule_seeded(seed):
    nbc_slugs = {r["slug"] for r in seed if r["subcategory"] == "nbc"}
    for rule_key in codes_kb.NBC_INDIA.keys():
        assert f"code_nbc_{rule_key}" in nbc_slugs


def test_nbc_minimum_room_dim_data_matches(seed):
    by_slug = {r["slug"]: r for r in seed}
    row = by_slug["code_nbc_minimum_room_dimensions"]
    legacy = codes_kb.NBC_INDIA["minimum_room_dimensions"]
    for k in (
        "habitable_room_min_area_m2",
        "habitable_room_min_short_side_m",
        "habitable_room_min_height_m",
        "kitchen_min_area_m2",
        "bathroom_min_area_m2",
    ):
        assert row["data"][k] == legacy[k]


def test_nbc_carries_part_in_source_section(seed):
    by_slug = {r["slug"]: r for r in seed}
    row = by_slug["code_nbc_fire_egress"]
    assert "Part 4" in (row["source_section"] or "")


def test_ecbc_seeded(seed):
    row = next((r for r in seed if r["slug"] == "code_ecbc_envelope_targets"), None)
    assert row is not None
    assert row["data"]["envelope_U_value_wall_w_m2k"] == 0.40


def test_india_accessibility_and_fire_safety_seeded(seed):
    slugs = {r["slug"] for r in seed}
    assert "code_accessibility_india_general" in slugs
    assert "code_fire_safety_india_general" in slugs


# ─────────────────────────────────────────────────────────────────────
# IBC
# ─────────────────────────────────────────────────────────────────────


def test_every_ibc_occupancy_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for group in ibc_kb.OCCUPANCY_GROUPS.keys():
        assert f"code_ibc_occupancy_{group}" in slugs


def test_every_ibc_construction_type_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for ctype in ibc_kb.CONSTRUCTION_TYPES.keys():
        normalised = ctype.lower().replace("-", "_")
        assert f"code_ibc_construction_{normalised}" in slugs


def test_ibc_egress_and_accessibility_seeded(seed):
    by_slug = {r["slug"]: r for r in seed}
    egress = by_slug["code_ibc_egress"]
    assert egress["data"]["doorway"]["min_clear_width_mm"] == 815
    accessibility = by_slug["code_ibc_accessibility"]
    assert accessibility["jurisdiction"] == "international_ibc"


def test_iecc_envelope_per_zone_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for zone in ibc_kb.ENERGY_ENVELOPE_U_VALUES_W_M2K.keys():
        assert f"code_iecc_envelope_{zone}" in slugs


# ─────────────────────────────────────────────────────────────────────
# Structural
# ─────────────────────────────────────────────────────────────────────


def test_structural_topics_seeded(seed):
    expected = {
        "code_structural_live_loads_is875",
        "code_structural_dead_loads",
        "code_structural_wind_loads_is875",
        "code_structural_seismic_zones_is1893",
        "code_structural_column_spacing",
        "code_structural_span_limits",
        "code_structural_foundation_by_soil",
        "code_structural_material_strengths",
    }
    slugs = {r["slug"] for r in seed}
    assert expected.issubset(slugs)


def test_live_loads_data_intact(seed):
    by_slug = {r["slug"]: r for r in seed}
    row = by_slug["code_structural_live_loads_is875"]
    assert row["data"]["loads_kn_per_m2"] == structural_kb.LIVE_LOADS_KN_PER_M2


# ─────────────────────────────────────────────────────────────────────
# Climate
# ─────────────────────────────────────────────────────────────────────


def test_every_climate_zone_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for zone_key in climate_kb.ZONES.keys():
        assert f"code_climate_{zone_key}" in slugs


def test_climate_zone_pack_intact(seed):
    by_slug = {r["slug"]: r for r in seed}
    row = by_slug["code_climate_hot_dry"]
    legacy = climate_kb.ZONES["hot_dry"]
    assert row["data"]["display_name"] == legacy["display_name"]
    # Tuples coerced to lists.
    assert row["data"]["humidity_percent"] == [20, 40]


# ─────────────────────────────────────────────────────────────────────
# JSON-serialisability
# ─────────────────────────────────────────────────────────────────────


def test_all_data_dicts_json_serialisable(seed):
    import json

    json.dumps([r["data"] for r in seed], default=str)
