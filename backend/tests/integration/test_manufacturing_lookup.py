"""Integration tests for the Stage 3D manufacturing lookups.

Requires Postgres + ``alembic upgrade head``. Skipped automatically
without ``KATHA_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Seed presence
# ─────────────────────────────────────────────────────────────────────


async def test_manufacturing_rows_present(db_session):
    from app.repositories.standards import StandardsRepository

    repo = StandardsRepository(db_session)
    rows = await repo.list_active(category="manufacturing")
    assert len(rows) > 30, "expected ~40+ manufacturing rows after seed"
    subcats = {r["subcategory"] for r in rows}
    assert subcats == {
        "tolerance",
        "joinery",
        "welding",
        "lead_time",
        "moq",
        "qa_gate",
        "process_spec",
    }


# ─────────────────────────────────────────────────────────────────────
# Tolerance lookup parity with legacy
# ─────────────────────────────────────────────────────────────────────


async def test_tolerance_for_matches_legacy(db_session):
    from app.knowledge import manufacturing as legacy
    from app.services.standards import manufacturing_lookup as ml

    for category, spec in legacy.TOLERANCES.items():
        db_value = await ml.tolerance_for(db_session, category)
        assert db_value == float(spec["+-mm"]), (
            f"tolerance mismatch for {category}: legacy={spec['+-mm']}, db={db_value}"
        )


async def test_tolerance_for_unknown_returns_none(db_session):
    from app.services.standards import manufacturing_lookup as ml

    assert await ml.tolerance_for(db_session, "nonexistent_category") is None


# ─────────────────────────────────────────────────────────────────────
# Lead times + MOQ parity
# ─────────────────────────────────────────────────────────────────────


async def test_lead_time_for_matches_legacy(db_session):
    from app.knowledge import manufacturing as legacy
    from app.services.standards import manufacturing_lookup as ml

    for category, expected in legacy.LEAD_TIMES_WEEKS.items():
        result = await ml.lead_time_for(db_session, category)
        assert result is not None
        assert result == (int(expected[0]), int(expected[1]))


async def test_moq_for_matches_legacy(db_session):
    from app.knowledge import manufacturing as legacy
    from app.services.standards import manufacturing_lookup as ml

    for category, expected in legacy.MOQ.items():
        result = await ml.moq_for(db_session, category)
        assert result == int(expected)


# ─────────────────────────────────────────────────────────────────────
# Joinery + welding
# ─────────────────────────────────────────────────────────────────────


async def test_joinery_lookup_returns_full_spec(db_session):
    from app.services.standards import manufacturing_lookup as ml

    spec = await ml.joinery_lookup(db_session, "mortise_tenon")
    assert spec is not None
    assert spec["strength"] == "very high"
    assert spec["tolerance_mm"] == 0.5


async def test_welding_lookup(db_session):
    from app.services.standards import manufacturing_lookup as ml

    spec = await ml.welding_lookup(db_session, "GMAW_MIG")
    assert spec is not None
    assert "steel structural" in spec["use"]


# ─────────────────────────────────────────────────────────────────────
# QA gates ordering
# ─────────────────────────────────────────────────────────────────────


async def test_list_qa_gates_in_brd_canonical_order(db_session):
    from app.knowledge import manufacturing as legacy
    from app.services.standards import manufacturing_lookup as ml

    rows = await ml.list_qa_gates(db_session)
    assert len(rows) == 5
    stages = [r["data"]["stage"] for r in rows]
    assert stages == list(legacy.QUALITY_GATES_BRD_SPEC)


# ─────────────────────────────────────────────────────────────────────
# Process specs + precision
# ─────────────────────────────────────────────────────────────────────


async def test_process_spec_woodworking(db_session):
    from app.services.standards import manufacturing_lookup as ml

    spec = await ml.process_spec(db_session, "woodworking")
    assert spec is not None
    assert spec["lead_time_weeks"] == [4, 8]
    assert "mortise_tenon" in spec["joinery_core"]


async def test_precision_requirements(db_session):
    from app.services.standards import manufacturing_lookup as ml

    pr = await ml.precision_requirements(db_session)
    assert pr is not None
    assert pr["structural_mm"] == 1.0
    assert pr["cosmetic_mm"] == 2.0
    assert pr["material_thickness_mm"] == 0.5
    assert pr["hardware_placement_mm"] == 5.0


async def test_bending_rule(db_session):
    from app.services.standards import manufacturing_lookup as ml

    rule = await ml.bending_rule(db_session)
    assert rule is not None
    assert "thickness" in rule["rule"].lower()


# ─────────────────────────────────────────────────────────────────────
# Versioning
# ─────────────────────────────────────────────────────────────────────


async def test_admin_update_propagates_to_lookup(db_session):
    """Update tolerance for cosmetic from 2.0 → 2.5; lookup picks up new value."""
    from app.repositories.standards import StandardsRepository
    from app.services.standards import manufacturing_lookup as ml

    repo = StandardsRepository(db_session)

    before = await ml.tolerance_for(db_session, "cosmetic")
    assert before == 2.0

    await repo.update_data(
        slug="mfg_tolerance_cosmetic",
        category="manufacturing",
        new_data={
            "category": "cosmetic",
            "tolerance_plus_minus_mm": 2.5,
            "notes": "Tightened for premium pieces",
        },
        actor_id=None,
        reason="integration test bump",
    )
    await db_session.flush()

    after = await ml.tolerance_for(db_session, "cosmetic")
    assert after == 2.5
