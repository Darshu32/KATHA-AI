"""Phase 3 — tags on note_sections.

Adds a ``tags`` JSONB array column to ``note_sections``. Existing rows
get an empty array via ``server_default``, so this is a safe online
migration on a non-empty table.

Why JSONB instead of a join table
---------------------------------
Tag membership is always read-with-section and written-with-section;
we never need a "list every section with tag X across all my
notebooks" query at this stage. JSONB keeps the upsert path simple
(one row touched per save). If the query patterns shift, a follow-up
can introduce a ``note_section_tags`` join + GIN index without
breaking existing data.

Revision ID: 0026_notes_tags
Revises: 0025_notes
Create Date: 2026-05-06
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "0026_notes_tags"
down_revision = "0025_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "note_sections",
        sa.Column(
            "tags",
            JSONB,
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("note_sections", "tags")
