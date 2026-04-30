"""Integration tests for the Stage 3E codes + ergonomics lookups.

Requires Postgres + ``alembic upgrade head``. Skipped automatically
without ``KATHA_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Seed presence
# ─────────────────────────────────────────────────────────────────────


async def test_code_rows_present(db_session):
    from app.repositories.standards import StandardsRepository

    repo = StandardsRepository(db_session)
    rows_in = await repo.list_active(category="code", jurisdiction="india_nbc")
    rows_intl = await repo.list_active(
        category="code", jurisdiction="international_ibc"
    )
    assert len(rows_in) > 15, "expected ~25+ india_nbc code rows"
    assert len(rows_intl) > 15, "expected ~25+ international_ibc code rows"


async def test_ergonomics_rows_present(db_session):
    from app.repositories.standards import StandardsRepository

    repo = StandardsRepository(db_session)
    rows = await repo.list_active(
        category="space",
        subcategory="furniture_ergonomics",
        jurisdiction="india_nbc",
    )
    assert len(rows) >= 20  # 4 + 5 + 4 + 1 + 8 = 22


# ─────────────────────────────────────────────────────────────────────
# NBC parity with legacy
# ─────────────────────────────────────────────────────────────────────


async def test_check_room_against_nbc_matches_legacy(db_session):
    from app.knowledge import codes as legacy
    from app.services.standards import codes_lookup as cl

    # Bedroom too small (5 m² < 9.5).
    legacy_issues = legacy.check_room_against_nbc(
        room_type="bedroom", area_m2=5.0, short_side_m=2.0, height_m=2.5
    )
    db_issues = await cl.check_room_against_nbc(
        db_session,
        room_type="bedroom",
        area_m2=5.0,
        short_side_m=2.0,
        height_m=2.5,
    )
    assert len(db_issues) == len(legacy_issues)
    assert {i["issue"] for i in db_issues} == {i["issue"] for i in legacy_issues}


async def test_ecbc_targets_intact(db_session):
    from app.services.standards import codes_lookup as cl

    targets = await cl.get_ecbc_targets(db_session)
    assert targets is not None
    assert targets["envelope_U_value_wall_w_m2k"] == 0.40


# ─────────────────────────────────────────────────────────────────────
# IBC
# ─────────────────────────────────────────────────────────────────────


async def test_ibc_occupancy_groups(db_session):
    from app.services.standards import codes_lookup as cl

    groups = await cl.list_ibc_occupancy_groups(db_session)
    group_letters = {row["data"]["group"] for row in groups}
    assert {"A", "B", "R", "M"}.issubset(group_letters)


async def test_iecc_envelope_lookup(db_session):
    from app.services.standards import codes_lookup as cl

    spec = await cl.get_iecc_envelope(db_session, "climate_zone_2_hot")
    assert spec is not None
    assert spec["wall"] == 0.40


# ─────────────────────────────────────────────────────────────────────
# Structural
# ─────────────────────────────────────────────────────────────────────


async def test_check_span_matches_legacy(db_session):
    from app.knowledge import structural as legacy
    from app.services.standards import codes_lookup as cl

    # rcc_beam max 10 m. 12 m should warn_high.
    legacy_out = legacy.check_span("rcc_beam", 12.0)
    db_out = await cl.check_span(db_session, material="rcc_beam", span_m=12.0)
    assert legacy_out["status"] == db_out["status"] == "warn_high"


async def test_seismic_zones_intact(db_session):
    from app.services.standards import codes_lookup as cl

    data = await cl.get_seismic_zones(db_session)
    assert data is not None
    assert "zone_IV" in data["zones"]
    assert data["zones"]["zone_IV"]["z_factor"] == 0.24


# ─────────────────────────────────────────────────────────────────────
# Climate
# ─────────────────────────────────────────────────────────────────────


async def test_climate_zone_lookup_alias_tolerant(db_session):
    from app.services.standards import codes_lookup as cl

    for variant in ("hot_dry", "Hot-Dry", "HOT DRY"):
        zone = await cl.get_climate_zone(db_session, variant)
        assert zone is not None
        assert zone["display_name"] == "Hot & Dry"


async def test_list_climate_zones_returns_five(db_session):
    from app.services.standards import codes_lookup as cl

    rows = await cl.list_climate_zones(db_session)
    assert len(rows) == 5
    keys = {r["slug"].replace("code_climate_", "") for r in rows}
    assert keys == {"hot_dry", "warm_humid", "composite", "temperate", "cold"}


# ─────────────────────────────────────────────────────────────────────
# Ergonomics
# ─────────────────────────────────────────────────────────────────────


async def test_ergonomics_chair_lookup(db_session):
    from app.services.standards import ergonomics_lookup as el

    spec = await el.get_ergonomics(
        db_session, item_group="chair", item="dining_chair"
    )
    assert spec is not None
    assert spec["seat_height_mm"] == [400, 450]


async def test_ergonomics_check_range_matches_legacy(db_session):
    from app.knowledge import ergonomics as legacy
    from app.services.standards import ergonomics_lookup as el

    # Dining chair seat height 350 mm — below min 400.
    legacy_out = legacy.check_range(
        "chair", "dining_chair", "seat_height", 350.0
    )
    db_out = await el.check_range(
        db_session,
        category="chair",
        item="dining_chair",
        dim="seat_height",
        value_mm=350.0,
    )
    assert legacy_out["status"] == db_out["status"] == "warn_low"


async def test_under_bed_storage_band(db_session):
    from app.services.standards import ergonomics_lookup as el

    band = await el.bed_under_storage_band(db_session)
    assert band == (300, 400)


# ─────────────────────────────────────────────────────────────────────
# Versioning
# ─────────────────────────────────────────────────────────────────────


async def test_admin_update_propagates(db_session):
    """Update bedroom NBC min_area_m2 from 9.5 → 10.0; lookup picks up new value."""
    from app.repositories.standards import StandardsRepository
    from app.services.standards import codes_lookup as cl

    repo = StandardsRepository(db_session)

    before = await cl.nbc_minimum_room_dimensions(db_session)
    assert before["habitable_room_min_area_m2"] == 9.5

    new_data = dict(before)
    new_data["habitable_room_min_area_m2"] = 10.0

    await repo.update_data(
        slug="code_nbc_minimum_room_dimensions",
        category="code",
        new_data=new_data,
        actor_id=None,
        reason="integration test bump",
    )
    await db_session.flush()

    after = await cl.nbc_minimum_room_dimensions(db_session)
    assert after["habitable_room_min_area_m2"] == 10.0
