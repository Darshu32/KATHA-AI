"""Close BRD §1C finishes coverage — varnish + stain + leather care
+ honour BRD lacquer thickness verbatim.

Two changes, one migration:

1. Insert 4 new rows under ``category='materials'``, ``subcategory=
   'finish'``: oil-based varnish, water-based varnish, stain (with
   water/oil/alcohol bases), leather care (oil/wax + UV protection).

2. Update ``material_finish_lacquer_pu.data`` to record the BRD
   thickness band (0.5-1mm = 500-1000 μm) verbatim while preserving
   the commercial value (50-80 μm) on a separate field. A ``notes``
   field documents the disagreement — same transparent pattern used
   for foam density in migration 0032.

Revision ID: 0034_materials_finish_v2
Revises: 0033_materials_finishes_seed
Create Date: 2026-05-13
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.services.standards.materials_seed import build_finishes_brd_completion_rows

# revision identifiers, used by Alembic.
revision = "0034_materials_finish_v2"
down_revision = "0033_materials_finishes_seed"
branch_labels = None
depends_on = None


_LACQUER_BRD_PATCH: dict = {
    # BRD-stated value, kept verbatim alongside commercial reality.
    "thickness_microns": [500, 1000],
    "commercial_thickness_microns_typical": [50, 80],
    "brd_thickness_disagreement_note": (
        "BRD §1C records 0.5–1mm (500–1000 μm) dry film. Commercial "
        "polyurethane / nitrocellulose lacquer dries at ~50–80 μm "
        "across 2–3 coats. Validator does not warn on per-object "
        "thickness against the BRD value — re-verify source before "
        "citing to client."
    ),
}


def _standards_table() -> sa.Table:
    return sa.table(
        "building_standards",
        sa.column("id", sa.String),
        sa.column("slug", sa.String),
        sa.column("category", sa.String),
        sa.column("jurisdiction", sa.String),
        sa.column("subcategory", sa.String),
        sa.column("display_name", sa.String),
        sa.column("notes", sa.Text),
        sa.column("data", postgresql.JSONB),
        sa.column("source_section", sa.String),
        sa.column("source_doc", sa.String),
        sa.column("source", sa.String),
    )


def upgrade() -> None:
    # Step 1 — insert new finish rows.
    rows = build_finishes_brd_completion_rows()
    if rows:
        op.bulk_insert(_standards_table(), rows)

    # Step 2 — UPDATE lacquer_pu thickness fields to honour BRD verbatim.
    # Merge the patch into the existing JSONB ``data`` so we don't lose
    # the legacy fields (coats, sheen, cost_inr_m2).
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE building_standards "
            "SET data = data || CAST(:patch AS jsonb), "
            "    notes = :notes "
            "WHERE slug = 'material_finish_lacquer_pu' "
            "AND category = 'materials' "
            "AND is_current = TRUE "
            "AND deleted_at IS NULL"
        ),
        {
            "patch": json.dumps(_LACQUER_BRD_PATCH),
            "notes": _LACQUER_BRD_PATCH["brd_thickness_disagreement_note"],
        },
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Step 1 reverse — remove the 4 new finish rows.
    bind.execute(
        sa.text(
            "DELETE FROM building_standards "
            "WHERE source = 'seed:materials' "
            "AND category = 'materials' "
            "AND slug IN ("
            " 'material_finish_varnish_oil_based',"
            " 'material_finish_varnish_water_based',"
            " 'material_finish_stain',"
            " 'material_finish_leather_care'"
            ")"
        )
    )

    # Step 2 reverse — strip the BRD thickness fields from lacquer_pu.
    bind.execute(
        sa.text(
            "UPDATE building_standards "
            "SET data = (data "
            "  - 'commercial_thickness_microns_typical' "
            "  - 'brd_thickness_disagreement_note'"
            ") || jsonb_build_object('thickness_microns', "
            "  CAST(:legacy_thickness AS jsonb)), "
            "notes = NULL "
            "WHERE slug = 'material_finish_lacquer_pu' "
            "AND category = 'materials' "
            "AND is_current = TRUE "
            "AND deleted_at IS NULL"
        ),
        {"legacy_thickness": json.dumps([50, 80])},
    )
