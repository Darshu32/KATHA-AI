"""Stage 14b — project_type on projects table.

Brings the existing ProjectTypeEnum (lived only in the brief tool's
Pydantic layer) down to the persistence layer so a project's type is a
queryable column. Drives:

- prompt prefixing (image_service `_PROJECT_TYPE_VISUAL_HINTS`)
- knowledge filter (knowledge_injector `_SEGMENT_BY_PROJECT_TYPE`)
- per-type cost defaults
- per-type starter prompts in the UI

Adds three columns:
- ``project_type``     : enum-as-string, NOT NULL, default ``residential``
- ``project_sub_type`` : optional free-text (e.g. "villa", "boutique-hotel")
- ``project_scale``    : optional free-text (e.g. "single-unit", "tower")

Revision ID: 0024_project_type
Revises: 0023_stage12_live_feeds
Create Date: 2026-05-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_project_type"
down_revision = "0023_stage12_live_feeds"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "project_type",
            sa.String(32),
            nullable=False,
            server_default="residential",
        ),
    )
    op.add_column(
        "projects",
        sa.Column("project_sub_type", sa.String(120), nullable=True),
    )
    op.add_column(
        "projects",
        sa.Column("project_scale", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_projects_project_type",
        "projects",
        ["project_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_projects_project_type", table_name="projects")
    op.drop_column("projects", "project_scale")
    op.drop_column("projects", "project_sub_type")
    op.drop_column("projects", "project_type")
