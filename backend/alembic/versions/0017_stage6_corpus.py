"""Stage 6 — RAG knowledge corpus tables.

Brings the existing ``knowledge_documents`` + ``knowledge_chunks``
tables (Stage 0 baseline) up to RAG-grade by adding:

- Citation metadata on documents (jurisdiction, publisher, edition,
  total_pages, language, effective dates).
- Citation metadata on chunks (jurisdiction, page, page_end, section,
  chunk_index, total_chunks).
- An ``embedding vector(1536)`` column on chunks (matches OpenAI
  ``text-embedding-3-small``) with an IVFFlat cosine-ops index.
- A ``content_tsv`` Postgres tsvector column on chunks, populated by
  a trigger from ``content``, with a GIN index — this is the
  keyword side of hybrid retrieval. We use Postgres-native FTS
  rather than pulling in `rank_bm25` because it scales better and
  travels with the table.

Re-ingestion semantics
----------------------
Re-ingesting a document deletes the document row (CASCADE on the
FK already wired in the ORM) which drops every chunk for it. The
ingester then re-inserts. No partial updates — embeddings shift
under the hood when content changes, so the safer move is delete +
re-insert.

Why we don't drop the ``vector`` extension on downgrade
-------------------------------------------------------
Other tables (``project_memory_chunks`` from Stage 5B) depend on
the same extension. Migration 0016 already ensured it. We leave
it alone here.

Revision ID: 0017_stage6_corpus
Revises: 0016_stage5b_project_memory
Create Date: 2026-05-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0017_stage6_corpus"
down_revision = "0016_stage5b_project_memory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── pgvector extension (idempotent — Stage 5B also enables it) ──
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── knowledge_documents — Stage 6 columns ────────────────────────
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "jurisdiction",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "publisher",
            sa.String(200),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "edition",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "total_pages",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column(
            "language",
            sa.String(8),
            nullable=False,
            server_default="en",
        ),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("effective_from", sa.String(32), nullable=True),
    )
    op.add_column(
        "knowledge_documents",
        sa.Column("effective_to", sa.String(32), nullable=True),
    )
    op.create_index(
        "ix_knowledge_documents_jurisdiction",
        "knowledge_documents",
        ["jurisdiction"],
    )

    # ── knowledge_chunks — Stage 6 columns ───────────────────────────
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "jurisdiction",
            sa.String(64),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "page",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "page_end",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "section",
            sa.String(200),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "chunk_index",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "knowledge_chunks",
        sa.Column(
            "total_chunks",
            sa.Integer(),
            nullable=False,
            server_default="1",
        ),
    )

    # Embedding column — placeholder until we ALTER to vector(1536).
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding", sa.types.UserDefinedType(), nullable=True),
    )
    op.execute(
        "ALTER TABLE knowledge_chunks "
        "ALTER COLUMN embedding TYPE vector(1536) USING NULL::vector(1536)"
    )

    # tsvector column for hybrid retrieval — populated by a trigger.
    op.execute(
        "ALTER TABLE knowledge_chunks "
        "ADD COLUMN content_tsv tsvector"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION knowledge_chunks_tsv_trigger()
        RETURNS trigger AS $$
        BEGIN
          NEW.content_tsv := to_tsvector('english', coalesce(NEW.content, ''));
          RETURN NEW;
        END
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER knowledge_chunks_tsv_update
        BEFORE INSERT OR UPDATE OF content
        ON knowledge_chunks
        FOR EACH ROW EXECUTE FUNCTION knowledge_chunks_tsv_trigger();
        """
    )

    # Indexes for hybrid retrieval.
    op.create_index(
        "ix_knowledge_chunks_jurisdiction",
        "knowledge_chunks",
        ["jurisdiction"],
    )
    op.create_index(
        "ix_knowledge_chunks_doc_section",
        "knowledge_chunks",
        ["document_id", "section"],
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_embedding_cosine "
        "ON knowledge_chunks "
        "USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX ix_knowledge_chunks_content_tsv "
        "ON knowledge_chunks "
        "USING gin(content_tsv)"
    )


def downgrade() -> None:
    # ── knowledge_chunks ─────────────────────────────────────────────
    op.execute(
        "DROP INDEX IF EXISTS ix_knowledge_chunks_content_tsv"
    )
    op.execute(
        "DROP INDEX IF EXISTS ix_knowledge_chunks_embedding_cosine"
    )
    op.drop_index(
        "ix_knowledge_chunks_doc_section", table_name="knowledge_chunks"
    )
    op.drop_index(
        "ix_knowledge_chunks_jurisdiction", table_name="knowledge_chunks"
    )

    op.execute(
        "DROP TRIGGER IF EXISTS knowledge_chunks_tsv_update ON knowledge_chunks"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS knowledge_chunks_tsv_trigger()"
    )
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS content_tsv")
    op.drop_column("knowledge_chunks", "embedding")
    op.drop_column("knowledge_chunks", "total_chunks")
    op.drop_column("knowledge_chunks", "chunk_index")
    op.drop_column("knowledge_chunks", "section")
    op.drop_column("knowledge_chunks", "page_end")
    op.drop_column("knowledge_chunks", "page")
    op.drop_column("knowledge_chunks", "jurisdiction")

    # ── knowledge_documents ──────────────────────────────────────────
    op.drop_index(
        "ix_knowledge_documents_jurisdiction",
        table_name="knowledge_documents",
    )
    op.drop_column("knowledge_documents", "effective_to")
    op.drop_column("knowledge_documents", "effective_from")
    op.drop_column("knowledge_documents", "language")
    op.drop_column("knowledge_documents", "total_pages")
    op.drop_column("knowledge_documents", "edition")
    op.drop_column("knowledge_documents", "publisher")
    op.drop_column("knowledge_documents", "jurisdiction")

    # We leave the pgvector extension alone — Stage 5B's
    # project_memory_chunks still depends on it.
