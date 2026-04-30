"""Stage 3D — extend ``building_standards.category`` enum to include
``manufacturing``.

Stage 3B's check constraint allowed only ``clearance | space | mep |
code``. Stage 3D adds manufacturing rules (tolerances, joinery,
welding, lead times, MOQ, QA gates) — they don't fit any of those
categories, so we extend the enum.

Schema change is a check-constraint swap. Stage 3E (codes) won't need
another migration; ``code`` is already in the original list.

Revision ID: 0009_stage3d_mfg_category
Revises: 0008_stage3c_mep_seed
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0009_stage3d_mfg_category"
down_revision = "0008_stage3c_mep_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the old constraint, add a wider one.
    op.drop_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        type_="check",
    )
    op.create_check_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        "category IN ('clearance', 'space', 'mep', 'code', 'manufacturing')",
    )


def downgrade() -> None:
    # Refuse to downgrade if any manufacturing rows would be invalidated.
    # Caller must clear them first.
    op.drop_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        type_="check",
    )
    op.create_check_constraint(
        "ck_building_standards_category_enum",
        "building_standards",
        "category IN ('clearance', 'space', 'mep', 'code')",
    )
