"""Multi-region — add ``region`` to projects.

Drives currency (cost output) + jurisdiction (building-code citations)
per project. Canonical keys live in ``app.services.regions.REGIONS``.
Existing rows backfill to ``india`` to preserve home-market behaviour.

Revision ID: 0036_project_region
Revises: 0035_design_variations_seed
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0036_project_region"
down_revision = "0035_design_variations_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "region",
            sa.String(length=32),
            nullable=False,
            server_default="india",
        ),
    )
    op.create_index("ix_projects_region", "projects", ["region"])


def downgrade() -> None:
    op.drop_index("ix_projects_region", table_name="projects")
    op.drop_column("projects", "region")
