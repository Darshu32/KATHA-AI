"""Stage 3A — themes seed data.

Populates the ``themes`` table from ``app.knowledge.themes.THEMES``.
The legacy module stays in place to keep ~25 services from breaking
during the transition; Stage 4+ migrates them to read from DB.

Idempotent: the partial unique index on ``slug WHERE is_current = TRUE
AND deleted_at IS NULL`` blocks duplicate inserts. A re-run of this
migration after admin edits would still fail safely.

Revision ID: 0005_stage3a_themes_seed
Revises: 0004_stage3a_themes
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.themes.seed import build_theme_seed_rows

# revision identifiers, used by Alembic.
revision = "0005_stage3a_themes_seed"
down_revision = "0004_stage3a_themes"
branch_labels = None
depends_on = None


def _themes_table() -> sa.Table:
    return sa.table(
        "themes",
        sa.column("id", sa.String),
        sa.column("slug", sa.String),
        sa.column("display_name", sa.String),
        sa.column("era", sa.String),
        sa.column("description", sa.String),
        sa.column("status", sa.String),
        sa.column("rule_pack", postgresql.JSONB),
        sa.column("aliases", postgresql.ARRAY(sa.String)),
        sa.column("cloned_from_slug", sa.String),
        sa.column("preview_image_keys", postgresql.ARRAY(sa.String)),
        sa.column("source", sa.String),
    )


def upgrade() -> None:
    rows = build_theme_seed_rows()
    if rows:
        op.bulk_insert(_themes_table(), rows)


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text("DELETE FROM themes WHERE source LIKE 'seed:%'")
    )
