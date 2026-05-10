"""Phase 4 — image_url on note_sections.

Adds a nullable ``image_url`` TEXT column to ``note_sections`` so a
note can carry the auto-generated Deep Mode image alongside its text.

Why TEXT (and not JSONB or a storage_key reference)
---------------------------------------------------
The image provider currently returns a base64 data URI, not a
persistent storage reference. We embed the URI verbatim:

- Field name ``image_url`` is generic — a later migration to a real
  storage key (R2 / CDN / signed URL) is a value-shape change, not
  a schema change.
- Median image size today ~150–400KB base64-encoded. PostgreSQL
  TEXT handles single-MB rows comfortably; we'd revisit only if
  notebooks routinely cross 10MB.
- Nullable because most existing rows pre-date this column and not
  every Deep Mode response yields an image.

Revision ID: 0027_notes_image_url
Revises: 0026_notes_tags
Create Date: 2026-05-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027_notes_image_url"
down_revision = "0026_notes_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "note_sections",
        sa.Column("image_url", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("note_sections", "image_url")
