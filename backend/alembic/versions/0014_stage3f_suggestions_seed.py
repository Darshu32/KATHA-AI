"""Stage 3F — suggestion-chip seed data.

Loads the 4 chips that previously lived in the frontend's
``DEFAULT_SUGGESTIONS`` array — all tagged ``contexts=['chat_empty_hero']``,
``status='published'``.

Revision ID: 0014_stage3f_suggestions_seed
Revises: 0013_stage3f_suggestions
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.suggestions.seed import build_suggestion_seed_rows

# revision identifiers, used by Alembic.
revision = "0014_stage3f_suggestions_seed"
down_revision = "0013_stage3f_suggestions"
branch_labels = None
depends_on = None


def _suggestions_table() -> sa.Table:
    return sa.table(
        "suggestions",
        sa.column("id", sa.String),
        sa.column("slug", sa.String),
        sa.column("label", sa.String),
        sa.column("prompt", sa.Text),
        sa.column("description", sa.String),
        sa.column("contexts", postgresql.ARRAY(sa.String)),
        sa.column("weight", sa.Integer),
        sa.column("status", sa.String),
        sa.column("tags", postgresql.ARRAY(sa.String)),
        sa.column("source", sa.String),
    )


def upgrade() -> None:
    rows = build_suggestion_seed_rows()
    if rows:
        op.bulk_insert(_suggestions_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "DELETE FROM suggestions WHERE source LIKE 'seed:frontend%'"
        )
    )
