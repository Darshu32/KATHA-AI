"""Stage 3D — manufacturing seed data.

Loads tolerances, joinery, welding, lead times, MOQ, QA gates, and
process specs from :mod:`app.knowledge.manufacturing` into
``building_standards`` rows tagged ``category='manufacturing'``.

Depends on 0009 (category enum extension) — without 0009 the inserts
would fail the check constraint.

Revision ID: 0010_stage3d_mfg_seed
Revises: 0009_stage3d_mfg_category
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.manufacturing_seed import (
    build_manufacturing_seed_rows,
)

# revision identifiers, used by Alembic.
revision = "0010_stage3d_mfg_seed"
down_revision = "0009_stage3d_mfg_category"
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
    rows = build_manufacturing_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE category = 'manufacturing' AND source LIKE 'seed:manufacturing%'"
        )
    )
