"""Stage 3C — MEP seed data into ``building_standards``.

Schema is unchanged — Stage 3B's ``building_standards`` table accepts
``category='mep'`` rows. This migration just inserts the legacy
:mod:`app.knowledge.mep` constants as DB rows.

Subcategories used:
  - ``hvac``        — air changes, CFM/person, cooling load, duct velocity,
                      equipment band, duct sizing, register ratings
  - ``electrical``  — lux, circuit load, power density, fixture catalogue,
                      outlet catalogue, outlet rules, task recipes, layout
  - ``plumbing``    — DFU, WSFU, pipe sizing, slope, vent stack, traps,
                      water demand
  - ``system_cost`` — per-m² MEP system cost bands (HVAC / electrical /
                      plumbing / fire / low-voltage)

Revision ID: 0008_stage3c_mep_seed
Revises: 0007_stage3b_standards_seed
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.mep_seed import build_mep_seed_rows

# revision identifiers, used by Alembic.
revision = "0008_stage3c_mep_seed"
down_revision = "0007_stage3b_standards_seed"
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
    rows = build_mep_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE category = 'mep' AND source LIKE 'seed:mep%'"
        )
    )
