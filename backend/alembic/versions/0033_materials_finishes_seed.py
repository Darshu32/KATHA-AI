"""Seed finish materials into building_standards (BRD §1C).

Inserts ``category='materials'`` rows for the five finishes in the
``FINISHES`` Python literal: lacquer_pu, melamine, wax_oil,
powder_coat, anodise. No standalone BRD-band row — the BRD finish
palettes (natural/stain/lacquer/veneer for wood; powder coat/
anodize/polished/brushed for metal) already live on the wood +
metal BRD-band rows from migrations 0030 / 0031.

The ``materials`` category enum was added in 0030 — no schema
change here.

Closes the BRD §1C materials migration set:
  - 0030: wood
  - 0031: metals
  - 0032: upholstery (leather / fabric / foam)
  - 0033: finishes  ← this migration

Revision ID: 0033_materials_finishes_seed
Revises: 0032_materials_upholstery_seed
Create Date: 2026-05-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.materials_seed import build_finishes_seed_rows

# revision identifiers, used by Alembic.
revision = "0033_materials_finishes_seed"
down_revision = "0032_materials_upholstery_seed"
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
    rows = build_finishes_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE source = 'seed:materials' "
            "AND category = 'materials' "
            "AND slug LIKE 'material_finish_%'"
        )
    )
