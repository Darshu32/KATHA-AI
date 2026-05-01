"""Knowledge chunk repository — CRUD + hybrid search.

Two queries matter here:

1. **Vector cosine search** — ``embedding <=> :query`` ordered ASC.
2. **BM25-like keyword search** — ``content_tsv @@ plainto_tsquery(:q)``
   ranked by ``ts_rank_cd``.

The repo exposes both as separate methods. The retriever in
:mod:`app.corpus.retriever` calls them in parallel and merges the
candidate sets.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import KnowledgeChunk


@dataclass
class HybridSearchRow:
    """One ranked candidate from either side of hybrid retrieval."""

    chunk: KnowledgeChunk
    score: float
    distance: Optional[float] = None
    bm25_rank: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────


class KnowledgeChunkRepository:
    """Async repo for :class:`KnowledgeChunk`."""

    # ────────────────────────────────────────────────────────────────
    # Writes
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def insert_chunks(
        session: AsyncSession,
        *,
        document_id: str,
        jurisdiction: str,
        chunks: list[dict[str, Any]],
    ) -> list[KnowledgeChunk]:
        """Insert N chunks for a document.

        Each ``chunks[i]`` must have keys: ``content``, ``embedding``,
        ``page``, ``page_end``, ``section``, ``chunk_index``,
        ``total_chunks``, ``token_count``. Optional: ``metadata_``.
        """
        rows: list[KnowledgeChunk] = []
        for c in chunks:
            row = KnowledgeChunk(
                document_id=document_id,
                content=str(c.get("content") or ""),
                token_count=int(c.get("token_count") or 0),
                jurisdiction=jurisdiction,
                page=int(c.get("page") or 0),
                page_end=int(c.get("page_end") or 0),
                section=str(c.get("section") or ""),
                chunk_index=int(c.get("chunk_index") or 0),
                total_chunks=int(c.get("total_chunks") or 1),
                embedding=list(c.get("embedding") or []),
                metadata_=dict(c.get("metadata_") or c.get("extra") or {}),
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        return rows

    @staticmethod
    async def delete_for_document(
        session: AsyncSession,
        *,
        document_id: str,
    ) -> int:
        """Delete every chunk under a document. CASCADE on the FK
        also catches this when the parent doc is deleted, but the
        ingester wants to wipe + re-insert keeping the doc row."""
        result = await session.execute(
            delete(KnowledgeChunk).where(
                KnowledgeChunk.document_id == document_id,
            )
        )
        await session.flush()
        return int(result.rowcount or 0)

    # ────────────────────────────────────────────────────────────────
    # Reads
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def count(
        session: AsyncSession,
        *,
        jurisdiction: Optional[str] = None,
    ) -> int:
        stmt = select(func.count(KnowledgeChunk.id))
        if jurisdiction is not None:
            stmt = stmt.where(KnowledgeChunk.jurisdiction == jurisdiction)
        result = await session.execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        chunk_id: str,
    ) -> Optional[KnowledgeChunk]:
        result = await session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.id == chunk_id)
        )
        return result.scalar_one_or_none()

    # ────────────────────────────────────────────────────────────────
    # Vector search
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def vector_search(
        session: AsyncSession,
        *,
        query_embedding: list[float],
        jurisdiction: Optional[str] = None,
        document_id: Optional[str] = None,
        top_k: int = 20,
    ) -> list[HybridSearchRow]:
        """Cosine-distance search across the corpus.

        ``top_k`` is generally larger than the user-facing top-K (we
        pull more candidates and re-rank). Caller decides how many
        survive the merge.
        """
        if not query_embedding:
            return []

        col = KnowledgeChunk.embedding
        try:
            distance = col.cosine_distance(query_embedding)  # type: ignore[attr-defined]
        except AttributeError:
            raise RuntimeError(
                "pgvector is not installed — cosine_distance unavailable."
            )

        stmt = (
            select(KnowledgeChunk, distance.label("distance"))
            .order_by(distance.asc())
            .limit(max(1, min(int(top_k), 200)))
        )
        if jurisdiction:
            stmt = stmt.where(KnowledgeChunk.jurisdiction == jurisdiction)
        if document_id:
            stmt = stmt.where(KnowledgeChunk.document_id == document_id)

        result = await session.execute(stmt)
        rows: list[HybridSearchRow] = []
        for chunk, dist in result.all():
            similarity = max(-1.0, min(1.0, 1.0 - float(dist)))
            rows.append(HybridSearchRow(
                chunk=chunk,
                score=similarity,
                distance=float(dist),
            ))
        return rows

    # ────────────────────────────────────────────────────────────────
    # BM25-like keyword search via Postgres tsvector
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def keyword_search(
        session: AsyncSession,
        *,
        query: str,
        jurisdiction: Optional[str] = None,
        document_id: Optional[str] = None,
        top_k: int = 20,
    ) -> list[HybridSearchRow]:
        """Postgres FTS — ``ts_rank_cd`` against the GIN index on
        ``content_tsv``.

        We use ``plainto_tsquery`` so callers can pass natural
        language verbatim. ``ts_rank_cd`` favours documents where
        the matched terms cluster together — a closer analogue to
        BM25 than the simpler ``ts_rank``.
        """
        query = (query or "").strip()
        if not query:
            return []

        # Bind via SQLAlchemy's ``text()`` so we keep the parameter
        # binding while using a column the ORM doesn't model.
        sql = (
            "SELECT id, ts_rank_cd(content_tsv, plainto_tsquery('english', :q)) "
            "AS bm25_rank "
            "FROM knowledge_chunks "
            "WHERE content_tsv @@ plainto_tsquery('english', :q) "
        )
        params: dict[str, Any] = {"q": query}
        if jurisdiction:
            sql += "AND jurisdiction = :jur "
            params["jur"] = jurisdiction
        if document_id:
            sql += "AND document_id = :did "
            params["did"] = document_id
        sql += (
            "ORDER BY bm25_rank DESC "
            "LIMIT :lim"
        )
        params["lim"] = max(1, min(int(top_k), 200))

        result = await session.execute(text(sql), params)
        scored: list[tuple[str, float]] = [
            (row.id, float(row.bm25_rank or 0.0))
            for row in result.all()
        ]
        if not scored:
            return []

        # Hydrate the chunks via a single IN-list lookup.
        ids = [s[0] for s in scored]
        rank_by_id = {sid: rank for sid, rank in scored}
        chunks_result = await session.execute(
            select(KnowledgeChunk).where(KnowledgeChunk.id.in_(ids))
        )
        chunks_by_id = {c.id: c for c in chunks_result.scalars().all()}

        rows: list[HybridSearchRow] = []
        for sid, rank in scored:
            ch = chunks_by_id.get(sid)
            if ch is None:
                continue
            rows.append(HybridSearchRow(
                chunk=ch,
                score=rank,
                bm25_rank=rank,
            ))
        return rows
