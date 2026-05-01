"""Stage 5 — chat session + message persistence (agent runtime memory).

Two append-only tables that back the agent's conversational state:

- ``chat_sessions`` — one row per ongoing conversation. Optionally
  scoped to a project (most chats are about a specific project; some
  triage chats aren't). Tracks message_count and last_message_at so
  the chat-list UI doesn't have to count rows.
- ``chat_messages`` — one row per persisted turn (user / assistant /
  tool). The ``content`` JSONB column carries the Anthropic-shaped
  blocks (text + tool_use + tool_result); other columns are
  denormalised previews used by the UI list view.

Why these aren't versioned-pattern tables
-----------------------------------------
Conversations are append-only by nature. There's no
``effective_from`` / ``effective_to`` for a chat message. We use the
plain ``UUIDMixin + TimestampMixin`` shape — no soft delete, no
version chain.

Revision ID: 0015_stage5_chat_sessions
Revises: 0014_stage3f_suggestions_seed
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0015_stage5_chat_sessions"
down_revision = "0014_stage3f_suggestions_seed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── chat_sessions ────────────────────────────────────────────────
    op.create_table(
        "chat_sessions",
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
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("last_message_at", sa.String(64), nullable=True),
        sa.Column(
            "message_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_chat_sessions_status_enum",
        ),
    )
    op.create_index("ix_chat_sessions_owner_id", "chat_sessions", ["owner_id"])
    op.create_index("ix_chat_sessions_project_id", "chat_sessions", ["project_id"])
    # Common list query: "show my recent chats for this project".
    op.create_index(
        "ix_chat_sessions_owner_recent",
        "chat_sessions",
        ["owner_id", "updated_at"],
    )

    # ── chat_messages ────────────────────────────────────────────────
    op.create_table(
        "chat_messages",
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
            "session_id",
            sa.String(32),
            sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("text_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "tool_call_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "elapsed_ms",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "input_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "output_tokens",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'tool')",
            name="ck_chat_messages_role_enum",
        ),
        sa.CheckConstraint(
            "position >= 1",
            name="ck_chat_messages_position_positive",
        ),
    )
    op.create_index(
        "ix_chat_messages_session_id",
        "chat_messages",
        ["session_id"],
    )
    # Two roles for the (session_id, position) index:
    # 1) Uniqueness — no two rows in the same session share a position.
    # 2) Range scan — "give me messages 1..N" for a session, ordered.
    op.create_index(
        "ix_chat_messages_session_position",
        "chat_messages",
        ["session_id", "position"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_chat_messages_session_position", table_name="chat_messages")
    op.drop_index("ix_chat_messages_session_id", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.drop_index("ix_chat_sessions_owner_recent", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_project_id", table_name="chat_sessions")
    op.drop_index("ix_chat_sessions_owner_id", table_name="chat_sessions")
    op.drop_table("chat_sessions")
