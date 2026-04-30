"""Integration tests for the Stage 1 pricing knowledge pipeline.

Requires a Postgres + Redis stack with migrations applied:

    docker compose up -d postgres redis migrate
    KATHA_INTEGRATION_TESTS=1 pytest backend/tests/integration

Skipped automatically without that env var (see conftest.py).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Knowledge dict shape & versioning
# ─────────────────────────────────────────────────────────────────────


async def test_build_pricing_knowledge_returns_brd_shape(db_session):
    """The DB-backed builder must produce the exact dict the cost-engine
    system prompt expects (so we don't need to update prompt + schema).
    """
    from app.services.pricing import build_pricing_knowledge

    knowledge = await build_pricing_knowledge(
        db_session,
        project_name="Test Project",
        piece_name="Test Piece",
        theme="modern",
        city="mumbai",
        market_segment="mass_market",
        complexity="moderate",
        hardware_piece_count=4,
    )

    # Top-level keys.
    for key in ("project", "cost_brd", "materials_kb", "source_versions"):
        assert key in knowledge

    # cost_brd must contain every BRD §4A constant the LLM expects.
    cb = knowledge["cost_brd"]
    for key in (
        "waste_factor_pct_band",
        "finish_cost_pct_of_material",
        "hardware_inr_per_piece",
        "workshop_overhead_pct_of_direct",
        "qc_pct_of_labor",
        "packaging_logistics_pct_of_product",
        "labor_rates_inr_hour",
        "trade_hours_by_complexity",
    ):
        assert key in cb, f"cost_brd missing required key: {key!r}"

    # Bands are 2-element lists [low, high].
    for band_key in (
        "waste_factor_pct_band",
        "finish_cost_pct_of_material",
        "hardware_inr_per_piece",
    ):
        band = cb[band_key]
        assert isinstance(band, list) and len(band) == 2
        assert band[0] <= band[1]


async def test_city_index_alias_resolution(db_session):
    """``bangalore`` and ``bengaluru`` should yield the same multiplier."""
    from app.services.pricing import build_pricing_knowledge

    a = await build_pricing_knowledge(
        db_session,
        project_name="x",
        piece_name="x",
        theme="",
        city="bangalore",
        market_segment="mass_market",
        complexity="moderate",
        hardware_piece_count=0,
    )
    b = await build_pricing_knowledge(
        db_session,
        project_name="x",
        piece_name="x",
        theme="",
        city="bengaluru",
        market_segment="mass_market",
        complexity="moderate",
        hardware_piece_count=0,
    )
    assert a["project"]["city_price_index"] == b["project"]["city_price_index"]


# ─────────────────────────────────────────────────────────────────────
# Snapshot capture + replay
# ─────────────────────────────────────────────────────────────────────


async def test_snapshot_round_trip(db_session):
    """Capture a knowledge dict, then load it back — must match exactly."""
    from app.services.pricing import (
        build_pricing_knowledge,
        load_snapshot,
        record_snapshot,
    )

    original = await build_pricing_knowledge(
        db_session,
        project_name="Snapshot Test",
        piece_name="Test",
        theme="modern",
        city="mumbai",
        market_segment="mass_market",
        complexity="moderate",
        hardware_piece_count=2,
    )
    snapshot = await record_snapshot(
        db_session,
        knowledge=original,
        target_type="cost_engine",
        actor_kind="test",
    )
    await db_session.flush()

    replayed = await load_snapshot(db_session, snapshot["id"])
    assert replayed == original


async def test_snapshot_immutable_after_price_update(db_session):
    """Update a price after capturing — the snapshot must NOT change."""
    from app.repositories.pricing import MaterialPriceRepository
    from app.services.pricing import (
        build_pricing_knowledge,
        load_snapshot,
        record_snapshot,
    )

    knowledge_before = await build_pricing_knowledge(
        db_session,
        project_name="Immutability Test",
        piece_name="t",
        theme="",
        city=None,
        market_segment="mass_market",
        complexity="moderate",
        hardware_piece_count=0,
    )
    snapshot = await record_snapshot(
        db_session,
        knowledge=knowledge_before,
        target_type="cost_engine",
        actor_kind="test",
    )
    await db_session.flush()

    # Mutate walnut price.
    repo = MaterialPriceRepository(db_session)
    walnut_before = knowledge_before["materials_kb"]["wood_inr_kg"]["walnut"]
    await repo.update_price(
        slug="walnut",
        region="global",
        new_low=walnut_before[0] + 100,
        new_high=walnut_before[1] + 100,
        actor_id=None,
        reason="immutability test",
    )
    await db_session.flush()

    # Replay — snapshot value still the original.
    replayed = await load_snapshot(db_session, snapshot["id"])
    assert replayed["materials_kb"]["wood_inr_kg"]["walnut"] == walnut_before

    # Fresh build — sees the new price.
    knowledge_after = await build_pricing_knowledge(
        db_session,
        project_name="Immutability Test",
        piece_name="t",
        theme="",
        city=None,
        market_segment="mass_market",
        complexity="moderate",
        hardware_piece_count=0,
    )
    walnut_after = knowledge_after["materials_kb"]["wood_inr_kg"]["walnut"]
    assert walnut_after[0] == walnut_before[0] + 100
    assert walnut_after[1] == walnut_before[1] + 100
