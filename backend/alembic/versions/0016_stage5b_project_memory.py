"""Stage 5B — project memory (RAG) tables.

Enables the ``vector`` Postgres extension and creates
``project_memory_chunks`` — the embedded-text store the agent
queries when the architect asks "what did we say about X" or
"recall the kitchen materials I picked yesterday".

Schema highlights
-----------------
- ``embedding vector(1536)`` matches OpenAI ``text-embedding-3-small``.
  Switching to a different model down the line means a new migration
  with a different dim — embeddings aren't portable across models.
- IVFFlat index on the embedding column for cosine search. We use
  ``vector_cosine_ops`` because OpenAI recommends cosine distance for
  their embedding models; the lists count (100) is a reasonable
  default for projects of up to ~100k chunks.
- A composite btree index on ``(project_id, source_type, source_id,
  source_version)`` so the indexer can cheap-find existing chunks for
  a source and replace them.

Re-indexing strategy
--------------------
Re-indexing is **delete + insert**. The composite index makes the
"delete prior chunks for this source" query fast. We deliberately
don't merge / update existing rows — embeddings change in non-
trivial ways when the source content shifts, so a fresh insert is
both simpler and safer.

Revision ID: 0016_stage5b_project_memory
Revises: 0015_stage5_chat_sessions
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "0016_stage5b_project_memory"
down_revision = "0015_stage5_chat_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pgvector extension ───────────────────────────────────────────
    # ``CREATE EXTENSION IF NOT EXISTS vector`` is idempotent — safe
    # on environments where the extension is already enabled.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── project_memory_chunks ────────────────────────────────────────
    op.create_table(
        "project_memory_chunks",
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
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            sa.String(32),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_type", sa.String(64), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column(
            "source_version",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "total_chunks",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "token_estimate",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        # Use raw DDL for the vector column so we don't take a runtime
        # dep on ``pgvector.alembic`` here — the type lives in the
        # extension and Postgres parses it natively.
        sa.Column(
            "embedding",
            sa.types.UserDefinedType(),
            nullable=False,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    # Replace the placeholder ``embedding`` column type with the real
    # ``vector(1536)``. We do this via raw DDL because Alembic doesn't
    # know how to render the pgvector ``Vector`` type without the
    # ``pgvector.alembic`` glue.
    op.execute(
        "ALTER TABLE project_memory_chunks "
        "ALTER COLUMN embedding TYPE vector(1536) USING NULL::vector(1536)"
    )

    # ── Indexes ──────────────────────────────────────────────────────
    op.create_index(
        "ix_project_memory_project_id",
        "project_memory_chunks",
        ["project_id"],
    )
    op.create_index(
        "ix_project_memory_logical_source",
        "project_memory_chunks",
        ["project_id", "source_type", "source_id", "source_version"],
    )
    op.create_index(
        "ix_project_memory_project_owner",
        "project_memory_chunks",
        ["project_id", "owner_id"],
    )

    # IVFFlat index for cosine similarity search. ``lists = 100`` is a
    # standard starting point — pgvector's docs recommend ``rows / 1000``
    # for large tables. We can tune later if the project memory grows
    # past a few hundred thousand chunks.
    op.execute(
        "CREATE INDEX ix_project_memory_embedding_cosine "
        "ON project_memory_chunks "
        "USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_project_memory_embedding_cosine")
    op.drop_index(
        "ix_project_memory_project_owner",
        table_name="project_memory_chunks",
    )
    op.drop_index(
        "ix_project_memory_logical_source",
        table_name="project_memory_chunks",
    )
    op.drop_index(
        "ix_project_memory_project_id",
        table_name="project_memory_chunks",
    )
    op.drop_table("project_memory_chunks")
    # We don't drop the ``vector`` extension — other tables (e.g.
    # ``knowledge_chunks`` from the Stage-0 baseline) may use it.
