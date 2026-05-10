"""Backfill ``rule_pack.visual_hint`` on the 10 stock themes.

Until now visual hints for the image-generation prompt lived only in a
Python dict (``app.services.image_service._THEME_VISUAL_HINTS``). The
``themes`` table was the source of truth for the UI dropdown — but
the image path fell back to the display name for any DB theme not
also in that Python dict. This migration unifies the two registries:
the same 10 strings now live in each theme's ``rule_pack``, and
``resolve_theme_visual_hint()`` reads from DB first.

The migration is idempotent: it only writes ``visual_hint`` for themes
that don't already have one. Re-runs on top of admin-edited values are
no-ops.

Revision ID: 0029_theme_visual_hints
Revises: 0028_design_version_prompt
Create Date: 2026-05-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0029_theme_visual_hints"
down_revision = "0028_design_version_prompt"
branch_labels = None
depends_on = None


# Verbatim from the Python source of truth. Kept here (not imported)
# so the migration is self-contained and won't drift if the original
# dict is later refactored.
_VISUAL_HINTS = {
    "modern": (
        "modern style — clean lines, neutral palette, natural materials, "
        "minimal ornamentation"
    ),
    "minimalist": (
        "minimalist style — restrained palette, lots of negative space, "
        "only essential elements"
    ),
    "contemporary": (
        "contemporary style — current trends, mixed materials, sculptural "
        "lighting, soft curves"
    ),
    "scandinavian": (
        "scandinavian style — pale wood, warm whites, hygge textures, "
        "cozy minimalism"
    ),
    "traditional": (
        "traditional style — classic ornamentation, rich woods, "
        "symmetrical layouts, warm palette"
    ),
    "rustic": (
        "rustic style — reclaimed wood, exposed beams, natural stone, "
        "earthy textures"
    ),
    "industrial": (
        "industrial style — exposed brick, raw steel, concrete floors, "
        "edison bulbs, utilitarian aesthetic"
    ),
    "bohemian": (
        "bohemian style — layered textiles, eclectic mix, warm color "
        "palette, plants, vintage pieces"
    ),
    "luxury": (
        "luxury style — premium materials, marble, brass, velvet, "
        "dramatic lighting, refined ornamentation"
    ),
    "coastal": (
        "coastal style — light blues and whites, weathered wood, natural "
        "fibers, breezy and bright"
    ),
}


def upgrade() -> None:
    conn = op.get_bind()
    for slug, hint in _VISUAL_HINTS.items():
        # jsonb_set with create_missing=true inserts the key when
        # absent. The WHERE clause keeps us idempotent: an admin who
        # has already supplied a custom hint isn't overwritten.
        conn.execute(
            sa.text(
                """
                UPDATE themes
                SET rule_pack = jsonb_set(
                    COALESCE(rule_pack, '{}'::jsonb),
                    '{visual_hint}',
                    to_jsonb(CAST(:hint AS text)),
                    true
                )
                WHERE slug = :slug
                  AND (
                    rule_pack IS NULL
                    OR rule_pack->>'visual_hint' IS NULL
                    OR rule_pack->>'visual_hint' = ''
                  )
                """
            ),
            {"slug": slug, "hint": hint},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for slug in _VISUAL_HINTS:
        conn.execute(
            sa.text(
                """
                UPDATE themes
                SET rule_pack = rule_pack - 'visual_hint'
                WHERE slug = :slug
                """
            ),
            {"slug": slug},
        )
