"""Integration tests for the Stage 3B standards repository.

Requires Postgres + ``alembic upgrade head``. Skipped automatically
without ``KATHA_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Seed verification
# ─────────────────────────────────────────────────────────────────────


async def test_clearance_rows_present(db_session):
    from app.repositories.standards import StandardsRepository

    repo = StandardsRepository(db_session)
    rows = await repo.list_active(category="clearance")
    slugs = {r["slug"] for r in rows}
    for required in (
        "door_main_entry", "door_interior", "door_bathroom",
        "corridor_residential", "corridor_commercial",
        "stair_residential", "stair_fire_escape",
        "circulation_around_bed",
        "egress_general",
    ):
        assert required in slugs, f"missing clearance: {required!r}"


async def test_space_rows_present(db_session):
    from app.repositories.standards import StandardsRepository

    repo = StandardsRepository(db_session)
    rows = await repo.list_active(category="space")
    slugs = {r["slug"] for r in rows}
    for required in (
        "bedroom", "kitchen", "bathroom",
        "office_workstation", "meeting_room",
        "hotel_room_standard", "restaurant_seating",
    ):
        assert required in slugs, f"missing space row: {required!r}"


# ─────────────────────────────────────────────────────────────────────
# Jurisdiction resolution
# ─────────────────────────────────────────────────────────────────────


async def test_resolver_falls_back_to_baseline(db_session):
    """Asking for a non-existent jurisdiction falls back to india_nbc."""
    from app.repositories.standards import StandardsRepository

    repo = StandardsRepository(db_session)
    row = await repo.resolve(
        slug="door_main_entry",
        category="clearance",
        jurisdiction="zomboland",  # doesn't exist
    )
    assert row is not None
    assert row["jurisdiction"] == "india_nbc"


async def test_resolver_prefers_specific_when_available(db_session):
    """Insert a maharashtra_dcr override; resolver picks it for that jurisdiction."""
    from app.repositories.standards import StandardsRepository
    from app.models.standards import BuildingStandard

    # Manually insert a maharashtra_dcr-specific corridor minimum.
    override = BuildingStandard(
        slug="corridor_residential",
        category="clearance",
        jurisdiction="maharashtra_dcr",
        subcategory="corridor",
        display_name="Residential Corridor (Maharashtra DCR)",
        data={"min_width_mm": 1000, "preferred_mm": 1200},
        source_section="Maharashtra DCR 2034 — clause X",
        source_doc="Maharashtra-DCR-2034",
        source="test:override",
    )
    db_session.add(override)
    await db_session.flush()

    repo = StandardsRepository(db_session)

    # Maharashtra-scoped resolution → override.
    mh = await repo.resolve(
        slug="corridor_residential",
        category="clearance",
        jurisdiction="maharashtra_dcr",
    )
    assert mh is not None
    assert mh["jurisdiction"] == "maharashtra_dcr"
    assert mh["data"]["min_width_mm"] == 1000

    # Other jurisdictions still see baseline.
    karnataka = await repo.resolve(
        slug="corridor_residential",
        category="clearance",
        jurisdiction="karnataka_kmc",
    )
    assert karnataka is not None
    assert karnataka["jurisdiction"] == "india_nbc"
    assert karnataka["data"]["min_width_mm"] == 800


# ─────────────────────────────────────────────────────────────────────
# Versioning
# ─────────────────────────────────────────────────────────────────────


async def test_update_creates_new_version(db_session):
    from app.repositories.standards import StandardsRepository

    repo = StandardsRepository(db_session)
    before = await repo.get_active(
        slug="door_interior", category="clearance",
    )
    assert before is not None
    assert before["version"] == 1

    await repo.update_data(
        slug="door_interior",
        category="clearance",
        new_data={"width_mm": [820, 920], "height_mm": [2050, 2150]},
        new_notes="Updated for accessibility upgrade",
        actor_id=None,
        reason="integration test",
    )
    await db_session.flush()

    after = await repo.get_active(
        slug="door_interior", category="clearance",
    )
    assert after["version"] == before["version"] + 1
    assert after["data"]["width_mm"] == [820, 920]


# ─────────────────────────────────────────────────────────────────────
# Check helpers
# ─────────────────────────────────────────────────────────────────────


async def test_check_door_width_helpers(db_session):
    from app.services.standards import check_door_width

    ok = await check_door_width(db_session, door_type="main_entry", width_mm=1100)
    assert ok["status"] == "ok"
    assert ok["source_section"] is not None

    too_narrow = await check_door_width(
        db_session, door_type="main_entry", width_mm=750
    )
    assert too_narrow["status"] == "warn_low"


async def test_check_room_area_uses_db(db_session):
    from app.services.standards import check_room_area

    # 9 m² is min for bedroom — pass.
    ok = await check_room_area(db_session, room_type="bedroom", area_m2=12.0)
    assert ok["status"] == "ok"

    # 5 m² is below 9.
    low = await check_room_area(db_session, room_type="bedroom", area_m2=5.0)
    assert low["status"] == "warn_low"
