"""Extend building_standards.category enum + seed wood materials.

Adds ``materials`` to the category check-constraint and bulk-inserts
BRD §1C wood rows (walnut / oak / teak / plywood / mdf / rubberwood
+ a BRD wide-envelope row). Mirrors the Stage 3D pattern used to
add ``manufacturing``.

Revision ID: 0030_materials_wood_seed
Revises: 0029_theme_visual_hints
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.materials_seed import build_materials_seed_rows

# revision identifiers, used by Alembic.
revision = "0030_materials_wood_seed"
down_revision = "0029_theme_visual_hints"
branch_labels = None
depends_on = None


_CATEGORIES_WITH_MATERIALS = (
    "category IN ('clearance', 'space', 'mep', 'code', 'manufacturing', 'materials')"
)
_CATEGORIES_WITHOUT_MATERIALS = (
    "category IN ('clearance', 'space', 'mep', 'code', 'manufacturing')"
)


def _standards_table() -> sa.Table:
    return sa.table(
        "building_standards",
        sa.column("id", sa.String),
        sa.column("slug", sa.String),
        sa.column("category", sa.String),
        sa.column("jurisdiction", sa.String),
        sa.column("subcategory", sa.String),
        sa.column("display_name", sa.String),
        sa.column("notes", sa.Text),
        sa.column("data", postgresql.JSONB),
        sa.column("source_section", sa.String),
        sa.column("source_doc", sa.String),
        sa.column("source", sa.String),
    )


def upgrade() -> None:
    # Step 1 — widen the category enum to allow 'materials'.
    op.drop_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        type_="check",
    )
    op.create_check_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        _CATEGORIES_WITH_MATERIALS,
    )

    # Step 2 — bulk-insert the BRD §1C wood rows.
    rows = build_materials_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    # Remove the seeded rows first so the narrower constraint can apply.
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE source = 'seed:materials' "
            "AND category = 'materials'"
        )
    )
    op.drop_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        type_="check",
    )
    op.create_check_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        _CATEGORIES_WITHOUT_MATERIALS,
    )
