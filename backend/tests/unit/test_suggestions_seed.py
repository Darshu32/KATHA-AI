"""Stage 3F suggestion-chip seed tests."""

from __future__ import annotations

import pytest


@pytest.fixture(scope="module")
def seed():
    from app.services.suggestions.seed import build_suggestion_seed_rows
    return build_suggestion_seed_rows()


def test_four_default_chips_seeded(seed):
    assert len(seed) == 4
    slugs = {r["slug"] for r in seed}
    expected = {
        "modern_villa_facade_ideas",
        "sustainable_material_options",
        "vastu_living_room_layout",
        "natural_lighting_tips",
    }
    assert slugs == expected


def test_every_row_has_required_fields(seed):
    for row in seed:
        for key in ("id", "slug", "label", "prompt", "contexts",
                    "weight", "status", "source"):
            assert key in row, f"row missing {key!r}"


def test_every_chip_published_for_chat_empty_hero(seed):
    for row in seed:
        assert row["status"] == "published"
        assert "chat_empty_hero" in row["contexts"]


def test_weights_are_in_valid_range(seed):
    for row in seed:
        assert 0 <= row["weight"] <= 1000


def test_every_row_has_seed_source_tag(seed):
    for row in seed:
        assert row["source"].startswith("seed:frontend")


def test_chips_have_tags(seed):
    for row in seed:
        assert row["tags"] is not None
        assert len(row["tags"]) >= 1
