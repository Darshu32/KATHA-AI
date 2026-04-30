"""Deterministic seed builder for the Stage 3A ``themes`` table.

Converts ``app.knowledge.themes.THEMES`` and its alias map into row dicts
ready for ``op.bulk_insert``. Pure functions — no DB, no network.

Aliases handling
----------------
The legacy module keeps a separate ``_ALIASES`` dict that maps loose
strings to canonical theme keys. We merge those into each theme's
``aliases`` array so the resolver can do the lookup in one query.

Example::

    Legacy:
      _ALIASES = {"midcentury": "mid_century_modern", "mcm": "mid_century_modern"}
    Seeded:
      themes(slug="mid_century_modern", aliases=["midcentury", "mcm"])
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import themes as legacy_themes


def _aliases_for_slug(slug: str) -> list[str] | None:
    """Aliases that should resolve to the given canonical slug."""
    aliases = sorted(
        alias for alias, target in legacy_themes._ALIASES.items() if target == slug
    )
    return aliases or None


def _description_for_pack(pack: dict[str, Any]) -> str | None:
    """Compose a short human-readable description from the rule pack.

    Stored separately from ``rule_pack`` so admin UIs can list themes
    without dragging the entire JSON blob.
    """
    bits: list[str] = []
    era = pack.get("era")
    if era:
        bits.append(f"Era: {era}")
    primary = (pack.get("material_palette") or {}).get("primary") or []
    if primary:
        bits.append("Primary materials: " + ", ".join(primary))
    intent = pack.get("ergonomic_intent")
    if intent:
        bits.append(f"Ergonomic intent: {intent}")
    return " · ".join(bits) if bits else None


def build_theme_seed_rows() -> list[dict[str, Any]]:
    """Every theme in :mod:`app.knowledge.themes` as an insertable row dict.

    Migration usage::

        from app.services.themes.seed import build_theme_seed_rows
        op.bulk_insert(themes_table, build_theme_seed_rows())

    Test usage::

        rows = build_theme_seed_rows()
        assert any(r["slug"] == "pedestal" for r in rows)
    """
    out: list[dict[str, Any]] = []
    for slug, pack in legacy_themes.THEMES.items():
        # Drop ``display_name`` from the rule pack — it lives as a
        # top-level column. This keeps the JSONB blob focused on
        # *parametric rules* and avoids two sources of truth.
        rule_pack = {k: v for k, v in pack.items() if k != "display_name"}
        out.append(
            {
                "id": uuid4().hex,
                "slug": slug,
                "display_name": pack.get("display_name") or slug.replace("_", " ").title(),
                "era": pack.get("era"),
                "description": _description_for_pack(pack),
                "status": "published",
                "rule_pack": rule_pack,
                "aliases": _aliases_for_slug(slug),
                "cloned_from_slug": None,
                "preview_image_keys": None,
                "source": "seed:knowledge.themes.THEMES",
            }
        )
    return out
