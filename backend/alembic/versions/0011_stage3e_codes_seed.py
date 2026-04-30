"""Stage 3E — codes seed (NBC + ECBC + IBC + structural + climate).

Loads building-code rows into the existing ``building_standards`` table.
``category='code'`` is already permitted by Stage 3B's check constraint;
no schema change needed.

Subcategories inserted:
  - ``nbc``           (NBC India room dimensions, ventilation, staircase, …)
  - ``ecbc``          (Energy Conservation Building Code targets)
  - ``accessibility`` (NBC India + IBC variants, jurisdiction-tagged)
  - ``fire_safety``   (NBC India quick reference)
  - ``ibc_*``         (IBC 2021 occupancy / construction / egress / env)
  - ``iecc``          (IECC envelope U-values per climate zone)
  - ``structural``    (IS-aligned loads, spans, seismic, foundations)
  - ``climate``       (5 NBC India climate zones)

Revision ID: 0011_stage3e_codes_seed
Revises: 0010_stage3d_mfg_seed
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.codes_seed import build_codes_seed_rows

# revision identifiers, used by Alembic.
revision = "0011_stage3e_codes_seed"
down_revision = "0010_stage3d_mfg_seed"
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
    rows = build_codes_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE category = 'code' AND ("
            "  source LIKE 'seed:codes%' OR "
            "  source LIKE 'seed:ibc%' OR "
            "  source LIKE 'seed:structural%' OR "
            "  source LIKE 'seed:climate%')"
        )
    )
