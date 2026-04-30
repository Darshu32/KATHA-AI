"""Stage 3F — suggestions table (schema only).

UX content for the chat empty-hero chips. Designers update via admin
endpoints; frontend reads via the public ``GET /api/v1/suggestions``
endpoint on every empty-state render.

Seed data is loaded by 0014_stage3f_suggestions_seed.py.

Revision ID: 0013_stage3f_suggestions
Revises: 0012_stage3e_ergonomics_seed
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0013_stage3f_suggestions"
down_revision = "0012_stage3e_ergonomics_seed"
branch_labels = None
depends_on = None


def _convention_columns() -> list[sa.Column]:
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "is_current",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("previous_version_id", sa.String(32), nullable=True),
        sa.Column(
            "effective_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("effective_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source",
            sa.String(64),
            nullable=False,
            server_default="seed",
        ),
        sa.Column("source_ref", sa.String(512), nullable=True),
        sa.Column(
            "created_by",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    ]


def _common_indexes(table: str) -> list[tuple[str, list[str]]]:
    return [
        (f"ix_{table}_is_current", ["is_current"]),
        (f"ix_{table}_deleted_at", ["deleted_at"]),
        (f"ix_{table}_effective_from", ["effective_from"]),
        (f"ix_{table}_effective_to", ["effective_to"]),
        (f"ix_{table}_source", ["source"]),
        (f"ix_{table}_created_by", ["created_by"]),
    ]


def upgrade() -> None:
    op.create_table(
        "suggestions",
        *_convention_columns(),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column(
            "contexts",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "weight",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="published",
        ),
        sa.Column("tags", postgresql.ARRAY(sa.String(64)), nullable=True),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_suggestions_status_enum",
        ),
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1000",
            name="ck_suggestions_weight_range",
        ),
    )
    op.create_index(
        "uq_suggestions_logical_current",
        "suggestions",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    op.create_index("ix_suggestions_status", "suggestions", ["status"])
    op.create_index("ix_suggestions_weight", "suggestions", ["weight"])
    for name, cols in _common_indexes("suggestions"):
        op.create_index(name, "suggestions", cols)


def downgrade() -> None:
    op.drop_table("suggestions")
