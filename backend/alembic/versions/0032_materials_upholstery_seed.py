"""Seed upholstery materials into building_standards (BRD §1C).

Inserts ``category='materials'`` rows for the BRD §1C upholstery
sub-section: leather (grades A-D), fabric (cotton / linen / wool /
synthetic blend / performance poly) and foam (HD36 / HR40 /
memory_foam) plus the BRD wide envelope row that aggregates the
three sub-families with their durability + colourfastness floors.

The ``materials`` category enum was added in migration
``0030_materials_wood_seed`` — no schema change here.

Foam density disagreement
-------------------------
The BRD envelope row records the BRD-stated values verbatim
(180 kg/m³, ₹150-400/m³). Per-foam rows carry commercial reality
(HD36 ~36 kg/m³ at ₹10-20k/m³). The validator does NOT compare
per-foam density against the BRD value — see the ``notes`` field on
``material_upholstery_brd_band`` for the reasoning.

Revision ID: 0032_materials_upholstery_seed
Revises: 0031_materials_metals_seed
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.materials_seed import build_upholstery_seed_rows

# revision identifiers, used by Alembic.
revision = "0032_materials_upholstery_seed"
down_revision = "0031_materials_metals_seed"
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
    rows = build_upholstery_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE source = 'seed:materials' "
            "AND category = 'materials' "
            "AND ("
            " slug LIKE 'material_upholstery_%' "
            " OR slug LIKE 'material_foam_%' "
            ")"
        )
    )
