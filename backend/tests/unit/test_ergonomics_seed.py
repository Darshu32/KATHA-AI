"""Stage 3E ergonomics seed-extraction tests."""

from __future__ import annotations

import pytest

from app.knowledge import ergonomics as ergo_kb


@pytest.fixture(scope="module")
def seed():
    from app.services.standards.ergonomics_seed import (
        build_ergonomics_seed_rows,
    )
    return build_ergonomics_seed_rows()


def test_every_row_in_space_furniture_ergonomics(seed):
    for row in seed:
        assert row["category"] == "space"
        assert row["subcategory"] == "furniture_ergonomics"
        assert row["jurisdiction"] == "india_nbc"
        assert row["source"].startswith("seed:ergonomics")


def test_every_chair_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for item in ergo_kb.CHAIRS.keys():
        assert f"ergonomics_chair_{item}" in slugs


def test_every_table_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for item in ergo_kb.TABLES.keys():
        assert f"ergonomics_table_{item}" in slugs


def test_every_bed_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for item in ergo_kb.BEDS.keys():
        assert f"ergonomics_bed_{item}" in slugs


def test_under_bed_storage_seeded(seed):
    slugs = {r["slug"] for r in seed}
    assert "ergonomics_bed_under_storage" in slugs


def test_every_storage_seeded(seed):
    slugs = {r["slug"] for r in seed}
    for item in ergo_kb.STORAGE.keys():
        assert f"ergonomics_storage_{item}" in slugs


def test_dining_chair_band_intact(seed):
    by_slug = {r["slug"]: r for r in seed}
    row = by_slug["ergonomics_chair_dining_chair"]
    assert row["data"]["item_group"] == "chair"
    # Tuples become lists in the JSONB-friendly form.
    assert row["data"]["seat_height_mm"] == [400, 450]
    assert row["data"]["seat_depth_mm"] == [450, 500]


def test_under_bed_storage_band_intact(seed):
    by_slug = {r["slug"]: r for r in seed}
    row = by_slug["ergonomics_bed_under_storage"]
    legacy_low, legacy_high = ergo_kb.BED_UNDER_STORAGE_MM
    assert row["data"]["under_storage_height_mm"] == [int(legacy_low), int(legacy_high)]


def test_total_row_count(seed):
    expected = (
        len(ergo_kb.CHAIRS)
        + len(ergo_kb.TABLES)
        + len(ergo_kb.BEDS)
        + 1  # under-bed storage special row
        + len(ergo_kb.STORAGE)
    )
    assert len(seed) == expected


def test_data_json_serialisable(seed):
    import json

    json.dumps([r["data"] for r in seed], default=str)
