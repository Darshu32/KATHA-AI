"""Persisted vision-grounded object hotspots.

The click-to-edit boxes on the rendered image are grounded to the actual
render (see ``app.services.object_grounding``) and stored per version so
re-opening a project reuses accurate boxes without another vision call.
Nullable — rows without it fall back to the deterministic plan projection
(``app.services.object_bboxes.compute_object_bboxes``).

Revision ID: 0039_object_bboxes
Revises: 0038_graph_normalization
Create Date: 2026-08-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0039_object_bboxes"
down_revision = "0038_graph_normalization"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "design_graph_versions",
        sa.Column("objects_bbox", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("design_graph_versions", "objects_bbox")
