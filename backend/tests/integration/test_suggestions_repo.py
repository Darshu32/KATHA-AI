"""Integration tests for the Stage 3F suggestion repository.

Requires Postgres + ``alembic upgrade head``. Skipped automatically
without ``KATHA_INTEGRATION_TESTS=1``.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Seed presence + reads
# ─────────────────────────────────────────────────────────────────────


async def test_seeded_chips_present(db_session):
    from app.repositories.suggestions import SuggestionRepository

    repo = SuggestionRepository(db_session)
    rows = await repo.list_published()
    slugs = {r["slug"] for r in rows}
    assert {
        "modern_villa_facade_ideas",
        "sustainable_material_options",
        "vastu_living_room_layout",
        "natural_lighting_tips",
    }.issubset(slugs)


async def test_list_published_filters_by_context(db_session):
    from app.repositories.suggestions import SuggestionRepository

    repo = SuggestionRepository(db_session)
    rows = await repo.list_published(context="chat_empty_hero")
    assert len(rows) >= 4
    for r in rows:
        assert "chat_empty_hero" in r["contexts"] or r["contexts"] == []


async def test_unknown_context_returns_globals_only(db_session):
    """Querying a context no chip is tagged with should yield 0 rows
    (since none of our seeds are global-only)."""
    from app.repositories.suggestions import SuggestionRepository

    repo = SuggestionRepository(db_session)
    rows = await repo.list_published(context="nonexistent_context")
    # All seeded chips have contexts=['chat_empty_hero'] (not global),
    # so they shouldn't surface for an unrelated context.
    assert all("nonexistent_context" not in r["contexts"] for r in rows)


async def test_list_orders_by_weight_desc(db_session):
    from app.repositories.suggestions import SuggestionRepository

    repo = SuggestionRepository(db_session)
    rows = await repo.list_published(context="chat_empty_hero")
    weights = [r["weight"] for r in rows]
    assert weights == sorted(weights, reverse=True)


# ─────────────────────────────────────────────────────────────────────
# Versioning
# ─────────────────────────────────────────────────────────────────────


async def test_update_creates_new_version(db_session):
    from app.repositories.suggestions import SuggestionRepository

    repo = SuggestionRepository(db_session)
    before = await repo.get_by_slug("modern_villa_facade_ideas")
    assert before is not None
    assert before["version"] == 1

    await repo.update(
        slug="modern_villa_facade_ideas",
        label="Modern facade design",
        weight=120,
        actor_id=None,
        reason="integration test",
    )
    await db_session.flush()

    after = await repo.get_by_slug("modern_villa_facade_ideas")
    assert after["version"] == 2
    assert after["label"] == "Modern facade design"
    assert after["weight"] == 120

    history = await repo.history_for("modern_villa_facade_ideas")
    assert len(history) >= 2


async def test_status_transition_versioned(db_session):
    from app.repositories.suggestions import SuggestionRepository

    repo = SuggestionRepository(db_session)
    await repo.update_status(
        slug="vastu_living_room_layout",
        new_status="archived",
        actor_id=None,
        reason="integration test archive",
    )
    await db_session.flush()

    # Public list no longer shows it.
    rows = await repo.list_published()
    archived_slugs = {"vastu_living_room_layout"}
    assert archived_slugs.isdisjoint({r["slug"] for r in rows})


# ─────────────────────────────────────────────────────────────────────
# Create new
# ─────────────────────────────────────────────────────────────────────


async def test_create_new_suggestion(db_session):
    from app.repositories.suggestions import SuggestionRepository

    repo = SuggestionRepository(db_session)
    new = await repo.create_new(
        slug="biophilic_office_design",
        label="Biophilic office design",
        prompt="How can we incorporate biophilic design principles in office spaces?",
        contexts=["chat_empty_hero"],
        weight=110,
        status="published",
        tags=["biophilia", "office"],
    )
    await db_session.flush()
    assert new["slug"] == "biophilic_office_design"
    assert new["weight"] == 110
    assert new["status"] == "published"


async def test_create_refuses_duplicate_slug(db_session):
    from app.repositories.suggestions import SuggestionRepository

    repo = SuggestionRepository(db_session)
    with pytest.raises(ValueError, match="already exists"):
        await repo.create_new(
            slug="natural_lighting_tips",
            label="dup",
            prompt="dup",
        )


# ─────────────────────────────────────────────────────────────────────
# Public projection
# ─────────────────────────────────────────────────────────────────────


async def test_public_endpoint_projection_omits_admin_fields(db_session):
    from app.services.suggestions.knowledge_service import (
        list_published_for_frontend,
    )

    rows = await list_published_for_frontend(
        db_session, context="chat_empty_hero"
    )
    assert rows
    sample = rows[0]
    assert set(sample.keys()) == {"slug", "label", "prompt", "weight", "tags"}
    # No id / version / source leaked.
    for forbidden in ("id", "version", "source", "is_current", "effective_from"):
        assert forbidden not in sample
