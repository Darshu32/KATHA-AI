"""Stage 3E — ergonomics seed (chairs / tables / beds / storage).

Adds furniture ergonomic ranges to ``building_standards`` under
``category='space'``, ``subcategory='furniture_ergonomics'``. Reuses
the existing ``space`` category so no enum extension is needed.

Revision ID: 0012_stage3e_ergonomics_seed
Revises: 0011_stage3e_codes_seed
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.ergonomics_seed import (
    build_ergonomics_seed_rows,
)

# revision identifiers, used by Alembic.
revision = "0012_stage3e_ergonomics_seed"
down_revision = "0011_stage3e_codes_seed"
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
    rows = build_ergonomics_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE category = 'space' "
            "  AND subcategory = 'furniture_ergonomics' "
            "  AND source LIKE 'seed:ergonomics%'"
        )
    )
