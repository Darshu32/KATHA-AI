"""Seed metal materials into building_standards (BRD §1C).

Inserts ``category='materials'`` rows for the primary metal palette
(mild steel / stainless steel / aluminium / brass) plus the BRD
wide envelope row. The ``materials`` category was added to the
check-constraint in migration ``0030_materials_wood_seed`` — no
schema change needed here.

Revision ID: 0031_materials_metals_seed
Revises: 0030_materials_wood_seed
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.materials_seed import build_metals_seed_rows

# revision identifiers, used by Alembic.
revision = "0031_materials_metals_seed"
down_revision = "0030_materials_wood_seed"
branch_labels = None
depends_on = None


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
    rows = build_metals_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE source = 'seed:materials' "
            "AND category = 'materials' "
            "AND subcategory IN ('metal', 'brd_band') "
            "AND slug LIKE 'material_metal_%'"
        )
    )
