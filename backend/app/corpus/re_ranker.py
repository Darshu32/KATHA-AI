"""Stage 6 re-ranker — optional cross-encoder seam.

The hybrid retriever pulls top-K candidates from the vector index
*and* the BM25 index. The two sets often overlap; the merged set
of unique chunks is then handed to a re-ranker which scores each
``(query, chunk)`` pair with a stronger model and re-orders.

A real cross-encoder (e.g. ``sentence-transformers/ms-marco-
MiniLM-L-12-v2``) typically pulls in PyTorch + ~80 MB of model
weights. That's a heavy dep for a project that may not always
need re-ranking — we ship a :class:`NoopReranker` by default and
let production swap in a real implementation by calling
``CorpusRetriever(reranker=MyCrossEncoder())``.

Why a class, not a function
---------------------------
Cross-encoder models are expensive to load — they want a single
instance held in memory, not re-instantiated per call. A class
gives us a place to hang state.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class RerankCandidate:
    """One ``(content, score, opaque_payload)`` tuple the re-ranker
    sees from the retriever.

    ``opaque`` is the original :class:`SearchHit` (or whatever the
    caller passes); the re-ranker doesn't inspect it, just shuffles
    it. This way we don't take a hard dep on the SearchHit shape
    here.
    """

    content: str
    score: float
    opaque: object


# ─────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────


class Reranker(ABC):
    """Async re-ranker.

    Implementations promise:

    - Output length ≤ input length (re-ranker may drop low-confidence hits).
    - Output ordering is *strictly* by descending re-rank score.
    - Each output's ``score`` is the new score (replaces the
      retriever's preliminary one).
    - Empty input → empty output, no API call.
    """

    name: str = "abstract"

    @abstractmethod
    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_k: int = 5,
    ) -> list[RerankCandidate]:
        ...


# ─────────────────────────────────────────────────────────────────────
# Noop default
# ─────────────────────────────────────────────────────────────────────


class NoopReranker(Reranker):
    """Default — keep the retriever's order, just truncate.

    The retriever's hybrid score (vector ∪ BM25 with a fixed alpha)
    is already a reasonable proxy for relevance. A real cross-
    encoder would do better but isn't always available.
    """

    name = "noop"

    async def rerank(
        self,
        query: str,
        candidates: list[RerankCandidate],
        *,
        top_k: int = 5,
    ) -> list[RerankCandidate]:
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda c: c.score, reverse=True)
        return ordered[: max(1, int(top_k))]


# ─────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────


def get_reranker() -> Reranker:
    """Return the configured re-ranker.

    Stage 6 ships :class:`NoopReranker` by default. A future stage
    can wire ``sentence-transformers`` here behind a settings flag.
    """
    return NoopReranker()
