"""Project memory retriever — read side of RAG.

Given a query string and a project, return the top-K most-relevant
chunks ranked by cosine similarity. Both the chunk content and a
similarity score (1 - cosine_distance, range 0..1) are surfaced so
the agent can decide how to use each hit.

Why a thin class
----------------
The retriever just chains "embed query → repo.search → pack hits"
but doing that in three places would scatter the embedder /
similarity-conversion concerns. Wrapping it makes the boundary
testable (inject a stub embedder, fake search rows).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.embeddings import Embedder, get_embedder
from app.repositories.project_memory import ProjectMemoryRepository

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Public hit type
# ─────────────────────────────────────────────────────────────────────


@dataclass
class SearchHit:
    """One ranked search result.

    - ``score`` is ``1 - cosine_distance`` so 1.0 = identical, 0.0 =
      orthogonal, < 0 = anti-correlated. The agent should treat
      ``score >= 0.7`` as confident and ``< 0.3`` as weak / probably
      irrelevant. (For ``StubEmbedder``, exact-string matches yield
      score 1.0 and unrelated strings yield ~0; semantic relationships
      only emerge with the real OpenAI embedder.)
    """

    source_type: str
    source_id: str
    source_version: str
    chunk_index: int
    total_chunks: int
    content: str
    score: float
    distance: float
    extra: dict[str, Any]


# ─────────────────────────────────────────────────────────────────────
# Retriever
# ─────────────────────────────────────────────────────────────────────


class ProjectMemoryRetriever:
    """Cosine-similarity search over a project's indexed chunks."""

    def __init__(self, embedder: Optional[Embedder] = None) -> None:
        self._embedder = embedder or get_embedder()

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    async def search(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        query: str,
        owner_id: Optional[str] = None,
        source_type: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchHit]:
        """Return up to ``top_k`` hits for the query.

        - ``owner_id`` is recommended in user-scoped contexts (the
          recall tool always passes it) so the search is doubly safe.
        - ``source_type`` filters on the source kind — pass
          ``"design_version"`` to scope to design states only,
          ``"plan_view"`` for plan drawings, etc. ``None`` searches
          everything.
        - ``top_k`` is clamped to [1, 50] at the repo layer.

        Empty / whitespace queries return an empty list (no API call,
        no DB scan).
        """
        query = (query or "").strip()
        if not query:
            return []

        vec = await self._embedder.embed_one(query)

        rows = await ProjectMemoryRepository.search(
            session,
            project_id=project_id,
            query_embedding=vec,
            owner_id=owner_id,
            source_type=source_type,
            top_k=top_k,
        )

        return [self._row_to_hit(chunk, distance) for chunk, distance in rows]

    @staticmethod
    def _row_to_hit(chunk, distance: float) -> SearchHit:
        # Cosine *similarity* in [-1, 1]. We invert from cosine
        # *distance* in [0, 2] (pgvector returns distance).
        similarity = 1.0 - distance
        # Clamp so callers see a tidy [-1, 1] range even in edge cases.
        similarity = max(-1.0, min(1.0, similarity))
        return SearchHit(
            source_type=str(getattr(chunk, "source_type", "") or ""),
            source_id=str(getattr(chunk, "source_id", "") or ""),
            source_version=str(getattr(chunk, "source_version", "") or ""),
            chunk_index=int(getattr(chunk, "chunk_index", 0) or 0),
            total_chunks=int(getattr(chunk, "total_chunks", 1) or 1),
            content=str(getattr(chunk, "content", "") or ""),
            score=round(similarity, 4),
            distance=round(distance, 4),
            extra=dict(getattr(chunk, "extra", None) or {}),
        )
