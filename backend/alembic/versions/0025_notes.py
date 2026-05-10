"""Phase 1 — server-side notes persistence.

Per-conversation notebooks: every Deep Mode response auto-creates a
``NoteSection`` row scoped to the originating chat. Notebooks are
implicit (the set of sections sharing a ``conversation_id``); no
parent ``notebooks`` table is materialised.

Schema notes
------------
- ``id`` is *client-supplied* (hex or hyphenated UUID). The frontend
  generates section IDs locally so optimistic UI works without a
  round-trip; the server upserts on that ID. Hence ``String(64)``,
  not the usual ``String(32)`` from ``UUIDMixin``.
- ``conversation_id`` is intentionally NOT a foreign key. Conversations
  currently live only in localStorage, so a strict FK would reject
  every insert. A future "sync conversations" migration will tighten
  this to a real FK.
- ``blocks`` is a JSONB array — see ``NoteBlock`` in
  ``frontend/lib/types.ts`` for the shape.
- ``ix_note_sections_owner_conversation`` covers the dominant query
  shape: "fetch this user's sections for this conversation".

Revision ID: 0025_notes
Revises: 0024_project_type
Create Date: 2026-05-06
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision = "0025_notes"
down_revision = "0024_project_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "note_sections",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.String(64), nullable=False),
        sa.Column("source_message_id", sa.String(64), nullable=True),
        sa.Column("title", sa.String(300), nullable=False, server_default="Notes"),
        sa.Column("blocks", JSONB, nullable=False, server_default="[]"),
        sa.Column("client_created_at", sa.String(64), nullable=True),
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
    )
    op.create_index(
        "ix_note_sections_owner_id",
        "note_sections",
        ["owner_id"],
    )
    op.create_index(
        "ix_note_sections_conversation_id",
        "note_sections",
        ["conversation_id"],
    )
    op.create_index(
        "ix_note_sections_owner_conversation",
        "note_sections",
        ["owner_id", "conversation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_note_sections_owner_conversation", table_name="note_sections")
    op.drop_index("ix_note_sections_conversation_id", table_name="note_sections")
    op.drop_index("ix_note_sections_owner_id", table_name="note_sections")
    op.drop_table("note_sections")
