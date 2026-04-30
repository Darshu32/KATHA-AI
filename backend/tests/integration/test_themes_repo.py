"""Integration tests for the Stage 3A theme repository.

Requires Postgres + `alembic upgrade head`. Skipped automatically
without ``KATHA_INTEGRATION_TESTS=1`` (see conftest).
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


# ─────────────────────────────────────────────────────────────────────
# Reads + alias resolution
# ─────────────────────────────────────────────────────────────────────


async def test_seed_rows_present_after_migrations(db_session):
    from app.repositories.themes import ThemeRepository

    repo = ThemeRepository(db_session)
    rows = await repo.list_active(status="published")
    slugs = {r["slug"] for r in rows}
    # All five BRD themes should be seeded by 0005.
    for required in (
        "pedestal", "contemporary", "modern", "mid_century_modern", "custom"
    ):
        assert required in slugs


async def test_alias_resolution(db_session):
    from app.repositories.themes import ThemeRepository

    repo = ThemeRepository(db_session)

    # All these strings should land on mid_century_modern.
    for alias in ("midcentury", "mid-century", "Mid Century", "MCM", "mcm"):
        row = await repo.get_active_by_slug(alias)
        assert row is not None, f"alias {alias!r} did not resolve"
        assert row["slug"] == "mid_century_modern"

    # Pedestal aliases.
    for alias in ("plinth", "theme_v"):
        row = await repo.get_active_by_slug(alias)
        assert row is not None
        assert row["slug"] == "pedestal"


# ─────────────────────────────────────────────────────────────────────
# Versioning
# ─────────────────────────────────────────────────────────────────────


async def test_update_creates_new_version(db_session):
    from app.repositories.themes import ThemeRepository

    repo = ThemeRepository(db_session)
    before = await repo.get_active_by_slug("modern")
    assert before["version"] == 1

    # Bump rule_pack with a tiny change.
    new_pack = dict(before["rule_pack"])
    new_pack["dos"] = list(new_pack.get("dos") or []) + ["test marker"]

    await repo.update_rule_pack(
        slug="modern",
        new_rule_pack=new_pack,
        actor_id=None,
        reason="integration test",
    )
    await db_session.flush()

    after = await repo.get_active_by_slug("modern")
    assert after["version"] == before["version"] + 1
    assert "test marker" in after["rule_pack"]["dos"]

    # History contains both versions.
    history = await repo.history_for_slug("modern")
    assert len(history) >= 2


# ─────────────────────────────────────────────────────────────────────
# Status workflow
# ─────────────────────────────────────────────────────────────────────


async def test_unpublish_hides_from_get_active_by_slug(db_session):
    from app.repositories.themes import ThemeRepository

    repo = ThemeRepository(db_session)
    # Use a clone to avoid breaking the seeded themes for other tests.
    clone = await repo.clone_theme(
        source_slug="modern",
        new_slug="modern_test_archive",
        new_display_name="Modern (test archive target)",
    )
    await db_session.flush()
    assert clone["status"] == "draft"

    # Drafts not visible to non-admin getter.
    public_view = await repo.get_active_by_slug("modern_test_archive")
    assert public_view is None

    # Admin getter sees them.
    admin_view = await repo.get_active_by_slug_admin("modern_test_archive")
    assert admin_view is not None and admin_view["status"] == "draft"


# ─────────────────────────────────────────────────────────────────────
# Cloning
# ─────────────────────────────────────────────────────────────────────


async def test_clone_creates_fresh_logical_record(db_session):
    from app.repositories.themes import ThemeRepository

    repo = ThemeRepository(db_session)
    source = await repo.get_active_by_slug("contemporary")
    assert source is not None

    new_slug = "contemporary_luxe_test"
    clone = await repo.clone_theme(
        source_slug="contemporary",
        new_slug=new_slug,
        new_display_name="Contemporary Luxe (test)",
        actor_id=None,
        reason="integration test clone",
    )
    await db_session.flush()

    assert clone["slug"] == new_slug
    assert clone["status"] == "draft"
    assert clone["version"] == 1
    assert clone["cloned_from_slug"] == "contemporary"
    # Rule pack copied verbatim.
    assert clone["rule_pack"] == source["rule_pack"]


async def test_clone_refuses_duplicate_slug(db_session):
    from app.repositories.themes import ThemeRepository

    repo = ThemeRepository(db_session)
    with pytest.raises(ValueError, match="already exists"):
        await repo.clone_theme(
            source_slug="modern",
            new_slug="modern",  # collision with seeded theme
            new_display_name="boom",
        )


# ─────────────────────────────────────────────────────────────────────
# DB-backed accessor returns the same shape as legacy
# ─────────────────────────────────────────────────────────────────────


async def test_db_accessor_matches_legacy_shape(db_session):
    from app.knowledge import themes as legacy_themes
    from app.services.themes import get_theme

    db_pack = await get_theme(db_session, "mid_century_modern")
    legacy_pack = legacy_themes.get("mid_century_modern")

    # display_name and era are surfaced on the rule_pack so callers
    # don't need to know about the column split.
    assert db_pack["display_name"] == legacy_pack["display_name"]
    # Material palette content matches.
    assert db_pack["material_palette"] == legacy_pack["material_palette"]
    assert db_pack["signature_moves"] == legacy_pack["signature_moves"]
