"""Stage 3B — building_standards table (schema only).

Single table for clearances, space requirements, and (later) MEP
targets and code clauses. Logical key: ``(slug, category, jurisdiction)``.

The table is deliberately wider than the Stage 3A themes table because
we want jurisdictional overrides — e.g. the BRD baseline clearance for
a residential corridor (800 mm) can be overridden by Maharashtra DCR
without losing the original.

Seed data is loaded by 0007_stage3b_standards_seed.py.

Revision ID: 0006_stage3b_standards
Revises: 0005_stage3a_themes_seed
Create Date: 2026-04-30
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0006_stage3b_standards"
down_revision = "0005_stage3a_themes_seed"
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
        "building_standards",
        *_convention_columns(),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column(
            "jurisdiction",
            sa.String(64),
            nullable=False,
            server_default="india_nbc",
        ),
        sa.Column("subcategory", sa.String(64), nullable=True),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "data",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("source_section", sa.String(200), nullable=True),
        sa.Column("source_doc", sa.String(120), nullable=True),
        sa.CheckConstraint(
            "category IN ('clearance', 'space', 'mep', 'code')",
            name="ck_building_standards_category_enum",
        ),
    )
    op.create_index(
        "uq_building_standards_logical_current",
        "building_standards",
        ["slug", "category", "jurisdiction"],
        unique=True,
        postgresql_where=sa.text("is_current = TRUE AND deleted_at IS NULL"),
    )
    op.create_index(
        "ix_building_standards_category_juris",
        "building_standards",
        ["category", "jurisdiction"],
    )
    op.create_index(
        "ix_building_standards_subcategory",
        "building_standards",
        ["subcategory"],
    )
    op.create_index("ix_building_standards_slug", "building_standards", ["slug"])
    for name, cols in _common_indexes("building_standards"):
        op.create_index(name, "building_standards", cols)


def downgrade() -> None:
    op.drop_table("building_standards")
