"""Stage 7 — uploaded assets table.

Tracks the metadata for binary uploads (images, sketches,
reference photos, future audio). The bytes themselves live in the
configured storage backend (local disk in dev, S3 / R2 in prod);
this table is the index of "what's there" + access control.

Lifecycle
---------
- ``uploading`` — row inserted by the route, before the storage
  backend confirms the write.
- ``ready`` — storage write succeeded; the asset is usable.
- ``error`` — storage write failed; ``error_message`` carries the
  exception type + message for the admin UI.

Indexes
-------
- ``(owner_id)`` — list "my uploads".
- ``(owner_id, created_at)`` — newest-first list view.
- ``(project_id)`` — list "uploads in this project".

Revision ID: 0018_stage7_uploaded_assets
Revises: 0017_stage6_corpus
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0018_stage7_uploaded_assets"
down_revision = "0017_stage6_corpus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "uploaded_assets",
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
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "kind",
            sa.String(64),
            nullable=False,
            server_default="image",
        ),
        sa.Column(
            "storage_backend",
            sa.String(16),
            nullable=False,
            server_default="local",
        ),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column(
            "original_filename",
            sa.String(255),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "mime_type",
            sa.String(64),
            nullable=False,
            server_default="application/octet-stream",
        ),
        sa.Column(
            "size_bytes",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "content_hash",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="ready",
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.CheckConstraint(
            "status IN ('uploading', 'ready', 'error')",
            name="ck_uploaded_assets_status_enum",
        ),
        sa.CheckConstraint(
            "size_bytes >= 0",
            name="ck_uploaded_assets_size_nonneg",
        ),
    )
    op.create_index(
        "ix_uploaded_assets_owner_id",
        "uploaded_assets",
        ["owner_id"],
    )
    op.create_index(
        "ix_uploaded_assets_project_id",
        "uploaded_assets",
        ["project_id"],
    )
    op.create_index(
        "ix_uploaded_assets_owner_recent",
        "uploaded_assets",
        ["owner_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_uploaded_assets_owner_recent",
        table_name="uploaded_assets",
    )
    op.drop_index(
        "ix_uploaded_assets_project_id",
        table_name="uploaded_assets",
    )
    op.drop_index(
        "ix_uploaded_assets_owner_id",
        table_name="uploaded_assets",
    )
    op.drop_table("uploaded_assets")
