"""Stage 3A — themes table (schema only, no seed).

Externalises ``app.knowledge.themes`` rule packs so designers can edit /
clone themes from an admin UI without code deploys.

Same convention columns as Stage 1 pricing tables — single
partial-unique index on ``slug WHERE is_current = TRUE AND
deleted_at IS NULL`` enforces "one current version per slug".

Seed data is loaded by 0005_stage3a_themes_seed.py.

Revision ID: 0004_stage3a_themes
Revises: 0003_stage1_pricing_seed
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0004_stage3a_themes"
down_revision = "0003_stage1_pricing_seed"
branch_labels = None
depends_on = None


# ─────────────────────────────────────────────────────────────────────
# Helpers — duplicated from 0002 because migrations should not import
# application code that may have changed since the migration was authored.
# ─────────────────────────────────────────────────────────────────────


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


# ─────────────────────────────────────────────────────────────────────
# Upgrade / downgrade
# ─────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    op.create_table(
        "themes",
        *_convention_columns(),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("era", sa.String(120), nullable=True),
        sa.Column("description", sa.String(2000), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="published",
        ),
        sa.Column(
            "rule_pack",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "aliases",
            postgresql.ARRAY(sa.String(64)),
            nullable=True,
        ),
        sa.Column("cloned_from_slug", sa.String(64), nullable=True),
        sa.Column(
            "preview_image_keys",
            postgresql.ARRAY(sa.String(512)),
            nullable=True,
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_themes_status_enum",
        ),
    )
    op.create_index(
        "uq_themes_logical_current",
        "themes",
        ["slug"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    op.create_index("ix_themes_slug", "themes", ["slug"])
    op.create_index("ix_themes_status", "themes", ["status"])
    for name, cols in _common_indexes("themes"):
        op.create_index(name, "themes", cols)


def downgrade() -> None:
    op.drop_table("themes")
