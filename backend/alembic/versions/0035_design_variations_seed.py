"""Extend building_standards.category enum + seed BRD §1C Design Variations.

Adds ``design`` to the category check-constraint and bulk-inserts the
five-axis BRD §1C Design Variations rows so :mod:`app.knowledge.
variations` becomes a seed source rather than the runtime authority.

Mirrors the Stage 3D / 3E enum-widen pattern used for ``manufacturing``
and ``materials``.

Revision ID: 0035_design_variations_seed
Revises: 0034_materials_finish_v2
Create Date: 2026-05-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.variations_seed import (
    build_design_variations_seed_rows,
)

# revision identifiers, used by Alembic.
revision = "0035_design_variations_seed"
down_revision = "0034_materials_finish_v2"
branch_labels = None
depends_on = None


_CATEGORIES_WITH_DESIGN = (
    "category IN ("
    "'clearance', 'space', 'mep', 'code', 'manufacturing', 'materials', 'design'"
    ")"
)
_CATEGORIES_WITHOUT_DESIGN = (
    "category IN ("
    "'clearance', 'space', 'mep', 'code', 'manufacturing', 'materials'"
    ")"
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
    # Step 1 — widen the category enum to allow 'design'.
    op.drop_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        type_="check",
    )
    op.create_check_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        _CATEGORIES_WITH_DESIGN,
    )

    # Step 2 — bulk-insert the BRD §1C design-variation rows.
    rows = build_design_variations_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()

    # Remove seeded rows so the narrower constraint can apply.
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE source = 'seed:design_variations' "
            "AND category = 'design'"
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
        _CATEGORIES_WITHOUT_DESIGN,
    )
