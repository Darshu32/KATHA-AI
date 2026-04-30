"""Stage 3F — Suggestion ORM model + metadata sanity."""

from __future__ import annotations

from app.models.suggestions import Suggestion


def test_suggestions_table_registered():
    from app.database import Base
    assert "suggestions" in {t.name for t in Base.metadata.tables.values()}


def test_suggestion_has_convention_columns():
    cols = {c.name for c in Suggestion.__table__.columns}
    for required in (
        "id", "created_at", "updated_at",
        "deleted_at",
        "version", "is_current", "previous_version_id",
        "effective_from", "effective_to",
        "source", "source_ref", "created_by",
    ):
        assert required in cols, f"Suggestion missing {required!r}"


def test_suggestion_has_business_columns():
    cols = {c.name for c in Suggestion.__table__.columns}
    for required in (
        "slug", "label", "prompt", "description",
        "contexts", "weight", "status", "tags",
    ):
        assert required in cols
