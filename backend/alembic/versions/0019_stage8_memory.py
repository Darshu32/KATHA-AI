"""Stage 8 — memory system tables.

Adds the four memory tables that back the Stage-8 agent surface:

- ``clients`` — minimal entity for studio clients (name + contact +
  primary_user_id). Multiple projects link to the same client via
  ``projects.client_id`` (nullable; existing projects are unset).
- ``client_profiles`` — aggregated patterns per client (typical
  budget, recurring rooms, accessibility flags). Refreshed by a
  Celery task. One row per client (UNIQUE on client_id).
- ``architect_profiles`` — per-user style fingerprint (preferred
  themes, materials, palette, typical room dims, tool-usage). One
  row per user (UNIQUE on user_id).
- ``design_decisions`` — append-only log of major design decisions
  per project. Indexed for "give me decisions for project X
  newest-first".

Plus two ALTERs:
- ``projects.client_id`` — nullable FK so existing rows are unaffected.
- ``users.learning_enabled`` — boolean privacy flag, defaults True.

Revision ID: 0019_stage8_memory
Revises: 0018_stage7_uploaded_assets
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0019_stage8_memory"
down_revision = "0018_stage7_uploaded_assets"
branch_labels = None
depends_on = None


def _common_columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    # ── ALTER users — learning_enabled ───────────────────────────────
    op.add_column(
        "users",
        sa.Column(
            "learning_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )

    # ── clients ──────────────────────────────────────────────────────
    op.create_table(
        "clients",
        *_common_columns(),
        sa.Column(
            "primary_user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "contact_email",
            sa.String(320),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "notes", sa.Text(), nullable=False, server_default="",
        ),
        sa.Column(
            "status", sa.String(32),
            nullable=False, server_default="active",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_clients_status_enum",
        ),
    )
    op.create_index(
        "ix_clients_primary_user_id", "clients", ["primary_user_id"],
    )

    # ── ALTER projects — client_id (after clients exists) ────────────
    op.add_column(
        "projects",
        sa.Column(
            "client_id",
            sa.String(32),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_projects_client_id", "projects", ["client_id"],
    )

    # ── client_profiles ──────────────────────────────────────────────
    op.create_table(
        "client_profiles",
        *_common_columns(),
        sa.Column(
            "client_id",
            sa.String(32),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "project_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "typical_budget_inr", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "recurring_room_types", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "recurring_themes", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "accessibility_flags", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "constraints", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_project_at", sa.String(32), nullable=True),
        sa.Column("last_extracted_at", sa.String(32), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # ── architect_profiles ───────────────────────────────────────────
    op.create_table(
        "architect_profiles",
        *_common_columns(),
        sa.Column(
            "user_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "project_count", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "preferred_themes", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "preferred_materials", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "preferred_palette_hexes", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "typical_room_dimensions_m", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "tool_usage", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("last_project_at", sa.String(32), nullable=True),
        sa.Column("last_extracted_at", sa.String(32), nullable=True),
        sa.Column(
            "metadata", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # ── design_decisions ─────────────────────────────────────────────
    op.create_table(
        "design_decisions",
        *_common_columns(),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "version", sa.Integer(),
            nullable=False, server_default="0",
        ),
        sa.Column(
            "category", sa.String(64),
            nullable=False, server_default="general",
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "rationale", sa.Text(),
            nullable=False, server_default="",
        ),
        sa.Column(
            "rejected_alternatives", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "sources", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "tags", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "metadata", postgresql.JSONB(),
            nullable=False, server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_design_decisions_project_id",
        "design_decisions",
        ["project_id"],
    )
    op.create_index(
        "ix_design_decisions_project_recent",
        "design_decisions",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_design_decisions_project_recent",
        table_name="design_decisions",
    )
    op.drop_index(
        "ix_design_decisions_project_id",
        table_name="design_decisions",
    )
    op.drop_table("design_decisions")
    op.drop_table("architect_profiles")
    op.drop_table("client_profiles")
    op.drop_index(
        "ix_projects_client_id", table_name="projects",
    )
    op.drop_column("projects", "client_id")
    op.drop_index("ix_clients_primary_user_id", table_name="clients")
    op.drop_table("clients")
    op.drop_column("users", "learning_enabled")
