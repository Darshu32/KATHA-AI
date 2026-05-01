"""Stage 6 hybrid retriever — vector ∪ BM25 → re-rank → top-K.

Pipeline
--------
1. Embed the query once.
2. Run vector search (top-N) and BM25/tsvector search (top-N) in
   parallel via :func:`asyncio.gather`.
3. Merge by chunk id with a fixed alpha (default 0.7 vector +
   0.3 BM25). Both scores are normalised into [0, 1] before mixing
   so the alpha actually means what it says.
4. Hand the merged candidate set to the re-ranker. Default re-ranker
   keeps the merged order; production can plug in a cross-encoder.
5. Return :class:`SearchHit` objects fully decorated with citation
   metadata.

Why merge before re-rank
------------------------
The vector index and the GIN index disagree on what's "relevant" —
vector picks up paraphrases, BM25 picks up exact code references
("§3.2.1"). Both are useful. We over-fetch from each and let the
re-ranker pick the final top-K from a richer candidate pool.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.corpus.re_ranker import (
    NoopReranker,
    RerankCandidate,
    Reranker,
    get_reranker,
)
from app.memory.embeddings import Embedder, get_embedder
from app.models.orm import KnowledgeDocument
from app.repositories.knowledge_corpus import (
    HybridSearchRow,
    KnowledgeChunkRepository,
)

log = logging.getLogger(__name__)


# Default mix between vector and BM25 — vector dominates, BM25 nudges
# exact-code-reference queries (e.g. "Part 4 §3.2") to the top.
DEFAULT_VECTOR_WEIGHT = 0.7
DEFAULT_BM25_WEIGHT = 0.3

# Over-fetch factor — pull this many candidates from each index
# before the re-ranker collapses to top-K.
CANDIDATE_OVERSAMPLE = 4


@dataclass
class SearchHit:
    """One ranked, fully-cited result from the corpus.

    The shape is the **citation contract** the agent owes the user:
    ``content`` is the verbatim chunk; ``source``, ``page``,
    ``section``, ``edition``, ``jurisdiction`` let the agent format
    a proper citation; ``retrieved_at`` is set by the agent layer
    when it builds its reply.
    """

    chunk_id: str
    document_id: str
    content: str
    source: str
    """Human-readable source label — typically ``"<title> (<edition>)"``."""

    jurisdiction: str
    page: int
    page_end: int
    section: str
    score: float
    """Final hybrid + re-rank score in [0, 1] (or [-1, 1] for stub
    embedder edge cases)."""

    vector_score: Optional[float] = None
    bm25_score: Optional[float] = None
    chunk_index: int = 0
    total_chunks: int = 1
    extra: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────
# Helpers — score normalisation
# ─────────────────────────────────────────────────────────────────────


def _normalise(values: list[float]) -> list[float]:
    """Scale a list of scores into [0, 1] via min-max.

    Preserves order. Returns all-1.0 if all values are identical
    (no information to spread).
    """
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi <= lo:
        return [1.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def _hybrid_merge(
    vector_rows: list[HybridSearchRow],
    bm25_rows: list[HybridSearchRow],
    *,
    vector_weight: float,
    bm25_weight: float,
) -> list[tuple[HybridSearchRow, float]]:
    """Merge by chunk id with a fixed mix.

    Returns ``[(row, blended_score), ...]`` sorted desc by score.
    """
    # Min-max normalise each side independently.
    vec_norm = _normalise([r.score for r in vector_rows])
    bm25_norm = _normalise([r.score for r in bm25_rows])

    by_id: dict[str, tuple[HybridSearchRow, float, float]] = {}
    for r, v in zip(vector_rows, vec_norm):
        by_id[r.chunk.id] = (r, v, 0.0)
    for r, v in zip(bm25_rows, bm25_norm):
        existing = by_id.get(r.chunk.id)
        if existing:
            row, v_score, _ = existing
            by_id[r.chunk.id] = (row, v_score, v)
        else:
            by_id[r.chunk.id] = (r, 0.0, v)

    blended: list[tuple[HybridSearchRow, float]] = []
    for row, v_score, b_score in by_id.values():
        score = vector_weight * v_score + bm25_weight * b_score
        blended.append((row, score))

    blended.sort(key=lambda t: t[1], reverse=True)
    return blended


# ─────────────────────────────────────────────────────────────────────
# Retriever
# ─────────────────────────────────────────────────────────────────────


class CorpusRetriever:
    """Hybrid search over the global knowledge corpus."""

    def __init__(
        self,
        embedder: Optional[Embedder] = None,
        reranker: Optional[Reranker] = None,
        *,
        vector_weight: float = DEFAULT_VECTOR_WEIGHT,
        bm25_weight: float = DEFAULT_BM25_WEIGHT,
    ) -> None:
        self._embedder = embedder or get_embedder()
        self._reranker = reranker or get_reranker()
        if abs((vector_weight + bm25_weight) - 1.0) > 1e-6:
            raise ValueError(
                f"vector_weight + bm25_weight must sum to 1.0, "
                f"got {vector_weight + bm25_weight}"
            )
        self._vw = float(vector_weight)
        self._bw = float(bm25_weight)

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    @property
    def reranker(self) -> Reranker:
        return self._reranker

    async def search(
        self,
        session: AsyncSession,
        *,
        query: str,
        jurisdiction: Optional[str] = None,
        document_id: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchHit]:
        """Run the full retrieval pipeline. Returns up to ``top_k`` hits."""
        query = (query or "").strip()
        if not query:
            return []

        oversample = max(top_k, top_k * CANDIDATE_OVERSAMPLE)

        # Embed the query first (we need this before parallelising).
        # The DB queries can run concurrently afterwards.
        query_vec = await self._embedder.embed_one(query)

        vector_task = KnowledgeChunkRepository.vector_search(
            session,
            query_embedding=query_vec,
            jurisdiction=jurisdiction,
            document_id=document_id,
            top_k=oversample,
        )
        bm25_task = KnowledgeChunkRepository.keyword_search(
            session,
            query=query,
            jurisdiction=jurisdiction,
            document_id=document_id,
            top_k=oversample,
        )

        vector_rows, bm25_rows = await asyncio.gather(vector_task, bm25_task)

        merged = _hybrid_merge(
            vector_rows,
            bm25_rows,
            vector_weight=self._vw,
            bm25_weight=self._bw,
        )
        if not merged:
            return []

        # Hand the merged set to the re-ranker.
        candidates = [
            RerankCandidate(content=row.chunk.content, score=score, opaque=row)
            for row, score in merged
        ]
        ranked = await self._reranker.rerank(query, candidates, top_k=top_k)
        if not ranked:
            return []

        # Hydrate citation metadata — pull doc titles + editions for
        # the final hits in one query so we don't N+1 the docs table.
        doc_ids = list({
            getattr(c.opaque, "chunk", None).document_id  # type: ignore[union-attr]
            for c in ranked if getattr(c, "opaque", None) is not None
        })
        docs_by_id: dict[str, KnowledgeDocument] = {}
        if doc_ids:
            result = await session.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.id.in_(doc_ids))
            )
            docs_by_id = {d.id: d for d in result.scalars().all()}

        hits: list[SearchHit] = []
        for cand in ranked:
            row: HybridSearchRow = cand.opaque  # type: ignore[assignment]
            ch = row.chunk
            doc = docs_by_id.get(ch.document_id)
            source_label = (
                f"{doc.title} ({doc.edition})" if doc and doc.edition
                else (doc.title if doc else "")
            )
            hits.append(SearchHit(
                chunk_id=ch.id,
                document_id=ch.document_id,
                content=ch.content,
                source=source_label,
                jurisdiction=ch.jurisdiction,
                page=int(ch.page or 0),
                page_end=int(ch.page_end or 0),
                section=str(ch.section or ""),
                score=round(float(cand.score), 4),
                vector_score=round(float(row.score), 4) if row.distance is not None else None,
                bm25_score=round(float(row.bm25_rank), 4) if row.bm25_rank is not None else None,
                chunk_index=int(ch.chunk_index or 0),
                total_chunks=int(ch.total_chunks or 1),
                extra=dict(ch.metadata_ or {}),
            ))
        return hits
