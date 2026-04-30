"""Stage 3B standards seed-extraction tests."""

from __future__ import annotations

import pytest

from app.knowledge import clearances as clearances_kb
from app.knowledge import space_standards as space_kb


@pytest.fixture(scope="module")
def seed():
    from app.services.standards.seed import build_standards_seed_rows
    return build_standards_seed_rows()


# ─────────────────────────────────────────────────────────────────────
# Top-level shape
# ─────────────────────────────────────────────────────────────────────


def test_every_row_has_required_fields(seed):
    for row in seed:
        for key in ("id", "slug", "category", "jurisdiction", "subcategory",
                    "display_name", "data", "source"):
            assert key in row, f"row missing {key!r}: {row}"
        assert row["category"] in {"clearance", "space"}
        assert row["jurisdiction"] == "india_nbc"
        assert row["source"].startswith("seed:")


def test_every_door_seeded(seed):
    door_slugs = {r["slug"] for r in seed if r["subcategory"] == "door"}
    legacy = {f"door_{s}" for s in clearances_kb.DOORS.keys()}
    assert legacy.issubset(door_slugs)


def test_every_corridor_seeded(seed):
    slugs = {r["slug"] for r in seed if r["subcategory"] == "corridor"}
    legacy = {f"corridor_{s}" for s in clearances_kb.CORRIDORS.keys()}
    assert legacy.issubset(slugs)


def test_every_stair_seeded(seed):
    slugs = {r["slug"] for r in seed if r["subcategory"] == "stair"}
    legacy = {f"stair_{s}" for s in clearances_kb.STAIRS.keys()}
    assert legacy.issubset(slugs)


def test_egress_collapsed_into_one_row(seed):
    egress_rows = [r for r in seed if r["subcategory"] == "egress"]
    assert len(egress_rows) == 1
    assert egress_rows[0]["slug"] == "egress_general"
    assert egress_rows[0]["data"]


def test_every_circulation_clearance_seeded(seed):
    circ_slugs = {r["slug"] for r in seed if r["subcategory"] == "circulation"}
    legacy = {f"circulation_{s}" for s in clearances_kb.CIRCULATION.keys()}
    assert legacy.issubset(circ_slugs)


# ─────────────────────────────────────────────────────────────────────
# Space standards
# ─────────────────────────────────────────────────────────────────────


def test_every_residential_room_seeded(seed):
    slugs = {r["slug"] for r in seed if r["subcategory"] == "residential_room"}
    assert set(space_kb.RESIDENTIAL.keys()).issubset(slugs)


def test_bedroom_data_matches_legacy(seed):
    bedroom = next(
        (r for r in seed if r["slug"] == "bedroom" and r["category"] == "space"),
        None,
    )
    assert bedroom is not None
    legacy = space_kb.RESIDENTIAL["bedroom"]
    assert bedroom["data"]["min_area_m2"] == legacy["min_area_m2"]
    assert bedroom["data"]["typical_area_m2"] == legacy["typical_area_m2"]
    # Notes copied to top-level column.
    assert bedroom["notes"] == legacy["notes"]


def test_door_main_entry_band_matches_legacy(seed):
    door = next(
        (r for r in seed if r["slug"] == "door_main_entry"), None
    )
    assert door is not None
    legacy = clearances_kb.DOORS["main_entry"]
    assert list(door["data"]["width_mm"]) == list(legacy["width_mm"])


def test_circulation_around_bed_matches_legacy(seed):
    row = next(
        (r for r in seed if r["slug"] == "circulation_around_bed"), None
    )
    assert row is not None
    assert row["data"]["clearance_mm"] == clearances_kb.CIRCULATION["around_bed"]


# ─────────────────────────────────────────────────────────────────────
# Source citations
# ─────────────────────────────────────────────────────────────────────


def test_nbc_rows_carry_source_doc(seed):
    nbc_rows = [r for r in seed if r["source_doc"] == "NBC-2016"]
    assert nbc_rows, "expected at least one NBC-tagged row (egress / stairs)"


def test_brd_rows_carry_source_doc(seed):
    brd_rows = [r for r in seed if r["source_doc"] == "BRD-Phase-1"]
    assert brd_rows, "expected BRD-tagged rows"
