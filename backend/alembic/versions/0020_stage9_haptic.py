"""Stage 9 — Haptic data structure (BRD Layer 7).

Adds the six haptic catalog tables and bulk-inserts seed rows so
any design in the system can produce a haptic export the moment
this migration runs:

- ``haptic_textures`` — one canonical texture per material, with a
  stable ``code`` hardware drivers reference (e.g. ``walnut_grain_001``)
  and a JSONB ``signature_data`` blob describing the texture
  parametrically (grain frequency, amplitude, pattern).
- ``haptic_thermal`` — perceived surface temperature in °C against a
  22 °C ambient. BRD-anchored: walnut → 28 °C, leather → 32 °C.
- ``haptic_friction`` — static friction coefficient against the
  human fingertip on a dry surface at room temp. BRD-anchored:
  wood → 0.35, leather → 0.40.
- ``haptic_firmness`` — soft / medium / firm + density (kg/m³) for
  perceived weight when the haptic arm lifts virtual objects.
- ``haptic_dimension_rules`` — per object_type (chair, sofa, desk,
  …) the adjustable axes, their ranges in mm, and a feedback curve
  describing proportion / linear-cost behaviour.
- ``haptic_feedback_loops`` — declarative rules tying dimension or
  material changes to cost / proportion responses, per the BRD
  examples ("1cm height change → ₹X cost change", "walnut → oak
  cost -₹Y", "proportions maintained within design intent").

No FK to materials. Materials are *keys* (strings) on the design
graph's ``graph_data`` JSONB; the haptic catalog is an external
lookup table indexed by the same key.

Revision ID: 0020_stage9_haptic
Revises: 0019_stage8_memory
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.haptic.seed import (
    build_dimension_rule_rows,
    build_feedback_loop_rows,
    build_firmness_rows,
    build_friction_rows,
    build_texture_rows,
    build_thermal_rows,
)

# revision identifiers, used by Alembic.
revision = "0020_stage9_haptic"
down_revision = "0019_stage8_memory"
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


# ── Lightweight sa.table builders for bulk_insert ────────────────────


def _haptic_textures_table() -> sa.Table:
    return sa.table(
        "haptic_textures",
        sa.column("id", sa.String),
        sa.column("name", sa.String),
        sa.column("code", sa.String),
        sa.column("material_id", sa.String),
        sa.column("signature_data", postgresql.JSONB),
    )


def _haptic_thermal_table() -> sa.Table:
    return sa.table(
        "haptic_thermal",
        sa.column("id", sa.String),
        sa.column("material_id", sa.String),
        sa.column("temperature_celsius", sa.Float),
        sa.column("source", sa.String),
    )


def _haptic_friction_table() -> sa.Table:
    return sa.table(
        "haptic_friction",
        sa.column("id", sa.String),
        sa.column("material_id", sa.String),
        sa.column("coefficient", sa.Float),
        sa.column("condition", sa.String),
    )


def _haptic_firmness_table() -> sa.Table:
    return sa.table(
        "haptic_firmness",
        sa.column("id", sa.String),
        sa.column("material_id", sa.String),
        sa.column("firmness_scale", sa.String),
        sa.column("density", sa.Float),
    )


def _haptic_dimension_rules_table() -> sa.Table:
    return sa.table(
        "haptic_dimension_rules",
        sa.column("id", sa.String),
        sa.column("object_type", sa.String),
        sa.column("adjustable_axes", postgresql.JSONB),
        sa.column("ranges", postgresql.JSONB),
        sa.column("feedback_curve", postgresql.JSONB),
    )


def _haptic_feedback_loops_table() -> sa.Table:
    return sa.table(
        "haptic_feedback_loops",
        sa.column("id", sa.String),
        sa.column("rule_key", sa.String),
        sa.column("trigger", postgresql.JSONB),
        sa.column("response", postgresql.JSONB),
        sa.column("formula", sa.String),
    )


def upgrade() -> None:
    # ── haptic_textures ──────────────────────────────────────────────
    op.create_table(
        "haptic_textures",
        *_common_columns(),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("material_id", sa.String(100), nullable=False),
        sa.Column(
            "signature_data",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_haptic_textures_material_id",
        "haptic_textures",
        ["material_id"],
    )

    # ── haptic_thermal ───────────────────────────────────────────────
    op.create_table(
        "haptic_thermal",
        *_common_columns(),
        sa.Column("material_id", sa.String(100), nullable=False),
        sa.Column(
            "temperature_celsius", sa.Float(), nullable=False,
        ),
        sa.Column(
            "source", sa.Text(),
            nullable=False, server_default="",
        ),
    )
    op.create_index(
        "ix_haptic_thermal_material_id",
        "haptic_thermal",
        ["material_id"],
        unique=True,
    )

    # ── haptic_friction ──────────────────────────────────────────────
    op.create_table(
        "haptic_friction",
        *_common_columns(),
        sa.Column("material_id", sa.String(100), nullable=False),
        sa.Column("coefficient", sa.Float(), nullable=False),
        sa.Column(
            "condition", sa.String(64),
            nullable=False, server_default="dry_room_temp",
        ),
    )
    op.create_index(
        "ix_haptic_friction_material_id",
        "haptic_friction",
        ["material_id"],
        unique=True,
    )

    # ── haptic_firmness ──────────────────────────────────────────────
    op.create_table(
        "haptic_firmness",
        *_common_columns(),
        sa.Column("material_id", sa.String(100), nullable=False),
        sa.Column(
            "firmness_scale", sa.String(32), nullable=False,
        ),
        sa.Column(
            "density", sa.Float(),
            nullable=False, server_default="0",
        ),
        sa.CheckConstraint(
            "firmness_scale IN ('soft', 'medium', 'firm')",
            name="ck_haptic_firmness_scale_enum",
        ),
    )
    op.create_index(
        "ix_haptic_firmness_material_id",
        "haptic_firmness",
        ["material_id"],
        unique=True,
    )

    # ── haptic_dimension_rules ───────────────────────────────────────
    op.create_table(
        "haptic_dimension_rules",
        *_common_columns(),
        sa.Column("object_type", sa.String(100), nullable=False),
        sa.Column(
            "adjustable_axes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "ranges",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "feedback_curve",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_index(
        "ix_haptic_dimension_rules_object_type",
        "haptic_dimension_rules",
        ["object_type"],
        unique=True,
    )

    # ── haptic_feedback_loops ────────────────────────────────────────
    op.create_table(
        "haptic_feedback_loops",
        *_common_columns(),
        sa.Column("rule_key", sa.String(120), nullable=False, unique=True),
        sa.Column(
            "trigger",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "response",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "formula", sa.Text(),
            nullable=False, server_default="",
        ),
    )

    # ── Seed data — runs in the same migration so a fresh ────────────
    # ── env always has a usable haptic catalog. ──────────────────────
    op.bulk_insert(_haptic_textures_table(), build_texture_rows())
    op.bulk_insert(_haptic_thermal_table(), build_thermal_rows())
    op.bulk_insert(_haptic_friction_table(), build_friction_rows())
    op.bulk_insert(_haptic_firmness_table(), build_firmness_rows())
    op.bulk_insert(
        _haptic_dimension_rules_table(), build_dimension_rule_rows(),
    )
    op.bulk_insert(
        _haptic_feedback_loops_table(), build_feedback_loop_rows(),
    )


def downgrade() -> None:
    op.drop_table("haptic_feedback_loops")
    op.drop_index(
        "ix_haptic_dimension_rules_object_type",
        table_name="haptic_dimension_rules",
    )
    op.drop_table("haptic_dimension_rules")
    op.drop_index(
        "ix_haptic_firmness_material_id", table_name="haptic_firmness",
    )
    op.drop_table("haptic_firmness")
    op.drop_index(
        "ix_haptic_friction_material_id", table_name="haptic_friction",
    )
    op.drop_table("haptic_friction")
    op.drop_index(
        "ix_haptic_thermal_material_id", table_name="haptic_thermal",
    )
    op.drop_table("haptic_thermal")
    op.drop_index(
        "ix_haptic_textures_material_id", table_name="haptic_textures",
    )
    op.drop_table("haptic_textures")
