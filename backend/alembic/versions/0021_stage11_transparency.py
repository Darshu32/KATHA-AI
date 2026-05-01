"""Stage 11 — reasoning transparency.

Adds the data structures the agent uses to make its thinking
visible and challengeable:

ALTER ``design_decisions`` (Stage 8 table):
- ``reasoning_steps`` JSONB  — ordered list of {step, observation,
  conclusion} dicts. Empty for legacy rows.
- ``confidence_score`` FLOAT — 0..1, nullable for rows authored
  before Stage 11.
- ``confidence_factors`` JSONB — list of human-readable contributors.
- ``provenance`` JSONB — banner snapshot at decision time.

NEW ``decision_challenges``:
- One row per architect challenge against a recorded decision.
- ``resolution`` ∈ {pending, rejected_challenge, decision_revised,
  accepted_override}. Pending = challenge filed, agent hasn't
  responded yet.
- ``new_decision_id`` (nullable FK) — when ``decision_revised`` or
  ``accepted_override`` create a successor decision, the link is
  preserved here so explain endpoints can walk the chain.
- ``response_reasoning`` Text — the agent's reply to the challenge.

Revision ID: 0021_stage11_transparency
Revises: 0020_stage9_haptic
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0021_stage11_transparency"
down_revision = "0020_stage9_haptic"
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
    # ── ALTER design_decisions ───────────────────────────────────────
    op.add_column(
        "design_decisions",
        sa.Column(
            "reasoning_steps",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "design_decisions",
        sa.Column(
            "confidence_score",
            sa.Float(),
            nullable=True,
        ),
    )
    op.add_column(
        "design_decisions",
        sa.Column(
            "confidence_factors",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "design_decisions",
        sa.Column(
            "provenance",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # ── decision_challenges ──────────────────────────────────────────
    op.create_table(
        "decision_challenges",
        *_common_columns(),
        sa.Column(
            "decision_id",
            sa.String(32),
            sa.ForeignKey("design_decisions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "challenger_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("challenge_text", sa.Text(), nullable=False),
        sa.Column(
            "resolution",
            sa.String(40),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "response_reasoning",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "new_decision_id",
            sa.String(32),
            sa.ForeignKey("design_decisions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "resolution IN ('pending', 'rejected_challenge', "
            "'decision_revised', 'accepted_override')",
            name="ck_decision_challenges_resolution_enum",
        ),
    )
    op.create_index(
        "ix_decision_challenges_project_recent",
        "decision_challenges",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_challenges_project_recent",
        table_name="decision_challenges",
    )
    op.drop_table("decision_challenges")
    op.drop_column("design_decisions", "provenance")
    op.drop_column("design_decisions", "confidence_factors")
    op.drop_column("design_decisions", "confidence_score")
    op.drop_column("design_decisions", "reasoning_steps")
