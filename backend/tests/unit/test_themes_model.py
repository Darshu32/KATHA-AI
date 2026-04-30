"""Stage 3A — Theme ORM model + metadata sanity."""

from __future__ import annotations

from app.models.themes import Theme


def test_themes_table_registered():
    from app.database import Base

    assert "themes" in {t.name for t in Base.metadata.tables.values()}


def test_theme_has_all_convention_columns():
    cols = {c.name for c in Theme.__table__.columns}
    for required in (
        "id",
        "created_at",
        "updated_at",
        "deleted_at",
        "version",
        "is_current",
        "previous_version_id",
        "effective_from",
        "effective_to",
        "source",
        "source_ref",
        "created_by",
    ):
        assert required in cols, f"Theme missing convention column {required!r}"


def test_theme_has_business_columns():
    cols = {c.name for c in Theme.__table__.columns}
    for required in (
        "slug",
        "display_name",
        "era",
        "description",
        "status",
        "rule_pack",
        "aliases",
        "cloned_from_slug",
        "preview_image_keys",
    ):
        assert required in cols
