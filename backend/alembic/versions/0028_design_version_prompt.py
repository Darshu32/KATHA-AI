"""Phase 1 — render-bake: capture the originating prompt on each design version.

The project pipeline (initial / edit / theme-switch) re-renders a 2D image
for every new graph version. To prompt the image model with full context
on edits and theme switches, the pipeline needs the design's *originating*
text prompt. Until now that text only lived in the request body that
created v1 — it wasn't persisted, so re-renders for v2+ had to be driven
client-side from a parallel /images/generate call.

This migration adds a nullable ``prompt`` TEXT column to
``design_graph_versions``. Every new version carries either the user-typed
prompt (initial), the prior version's prompt + edit hint (local edit), or
the prior version's prompt unchanged (theme switch). Existing rows stay
NULL, which is fine — the pipeline tolerates a missing prompt and skips
the render rather than failing.

Revision ID: 0028_design_version_prompt
Revises: 0027_notes_image_url
Create Date: 2026-05-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_design_version_prompt"
down_revision = "0027_notes_image_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "design_graph_versions",
        sa.Column("prompt", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("design_graph_versions", "prompt")
