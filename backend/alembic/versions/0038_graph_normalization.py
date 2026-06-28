"""Graph normalization provenance — raw graph + normalization report.

Every design graph now passes through a deterministic normalization +
validation chokepoint (``app.services.graph_normalizer``) before it is
persisted. ``graph_data`` holds the normalized graph; we additionally keep:

  * ``raw_graph_data``        — the original LLM output (provenance, debugging)
  * ``normalization_report``  — corrections applied + {ok, errors, warnings}

Both are nullable so pre-existing versions (written before this layer) keep
working; they simply have NULL provenance.

Revision ID: 0038_graph_normalization
Revises: 0037_intl_codes_seed
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0038_graph_normalization"
down_revision = "0037_intl_codes_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "design_graph_versions",
        sa.Column("raw_graph_data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "design_graph_versions",
        sa.Column(
            "normalization_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("design_graph_versions", "normalization_report")
    op.drop_column("design_graph_versions", "raw_graph_data")
