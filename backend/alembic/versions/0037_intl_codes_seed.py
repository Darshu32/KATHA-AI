"""International codes seed — Europe (Eurocode/DIN) + Middle East (UAE/Dubai).

Adds the two demo-critical jurisdictions so the compliance panel cites
the correct codes for Germany + Dubai client demos. ``category='code'``
is already permitted by Stage 3B's check constraint; no schema change.

Revision ID: 0037_intl_codes_seed
Revises: 0036_project_region
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.intl_codes_seed import build_intl_codes_seed_rows

# revision identifiers, used by Alembic.
revision = "0037_intl_codes_seed"
down_revision = "0036_project_region"
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
    rows = build_intl_codes_seed_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)


def downgrade() -> None:
    op.execute(
        "DELETE FROM building_standards "
        "WHERE source = 'seed:intl_codes' "
        "AND jurisdiction IN ('eu_eurocode', 'uae_dubai')"
    )
