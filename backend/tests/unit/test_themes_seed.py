"""Stage 3A theme seed-extraction tests.

Verifies the seed builder produces the expected shape and includes
all BRD themes.
"""

from __future__ import annotations

import pytest

from app.knowledge import themes as legacy_themes


@pytest.fixture(scope="module")
def seed_rows():
    from app.services.themes.seed import build_theme_seed_rows
    return build_theme_seed_rows()


def test_all_legacy_themes_seeded(seed_rows):
    seeded_slugs = {r["slug"] for r in seed_rows}
    legacy_slugs = set(legacy_themes.THEMES.keys())
    assert seeded_slugs == legacy_slugs, (
        f"missing in seed: {legacy_slugs - seeded_slugs}, "
        f"extra in seed: {seeded_slugs - legacy_slugs}"
    )


def test_brd_themes_present(seed_rows):
    """The BRD §2A names: Pedestal, Contemporary, Modern, Mid-Century Modern, Custom."""
    slugs = {r["slug"] for r in seed_rows}
    for required in ("pedestal", "contemporary", "modern", "mid_century_modern", "custom"):
        assert required in slugs, f"BRD theme missing: {required!r}"


def test_display_name_extracted(seed_rows):
    by_slug = {r["slug"]: r for r in seed_rows}
    assert by_slug["mid_century_modern"]["display_name"] == "Mid-Century Modern"
    assert by_slug["pedestal"]["display_name"] == "Pedestal"


def test_aliases_collapsed_onto_canonical_row(seed_rows):
    """Aliases from _ALIASES dict end up on the row they target."""
    by_slug = {r["slug"]: r for r in seed_rows}
    mcm = by_slug["mid_century_modern"]
    assert mcm["aliases"] is not None
    assert "midcentury" in mcm["aliases"]
    assert "mcm" in mcm["aliases"]

    pedestal = by_slug["pedestal"]
    assert pedestal["aliases"] is not None
    assert "plinth" in pedestal["aliases"]


def test_rule_pack_excludes_display_name(seed_rows):
    """display_name is a top-level column, not duplicated in rule_pack."""
    for row in seed_rows:
        assert "display_name" not in row["rule_pack"]


def test_rule_pack_preserves_signature_fields(seed_rows):
    by_slug = {r["slug"]: r for r in seed_rows}
    mcm = by_slug["mid_century_modern"]["rule_pack"]
    # BRD-listed signature elements survive the migration.
    assert "material_palette" in mcm
    assert "hardware" in mcm
    assert "signature_moves" in mcm
    assert "dos" in mcm
    assert "donts" in mcm


def test_every_row_tagged_with_seed_source(seed_rows):
    for row in seed_rows:
        assert row["source"].startswith("seed:")


def test_status_defaults_to_published(seed_rows):
    for row in seed_rows:
        assert row["status"] == "published"


def test_no_clone_lineage_on_seeds(seed_rows):
    """Initial seed rows are originals, not clones."""
    for row in seed_rows:
        assert row["cloned_from_slug"] is None
