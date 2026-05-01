"""Project memory indexer — turn an artefact into searchable chunks.

The indexer is the **write side** of project memory. The agent calls
it (directly or via the ``index_project_artefact`` tool) to make a
new design version, spec, cost run, or drawing semantically
retrievable.

Idempotency
-----------
Indexing the same logical source ``(project_id, source_type,
source_id, source_version)`` twice replaces the prior chunks rather
than duplicating them. The indexer:

1. Deletes existing rows for that key.
2. Re-chunks the new content.
3. Embeds the chunks.
4. Inserts fresh rows.

This is fine for the volumes we expect — a project with a few
hundred artefacts × a handful of chunks each. The DELETE uses the
``ix_project_memory_logical_source`` btree index so it stays fast
even on a populated table.

Failure semantics
-----------------
- Empty / whitespace artefacts: returns an :class:`IndexResult` with
  ``chunk_count=0`` — no error, just nothing to index.
- Embedder fails: re-raises :class:`EmbeddingError` so the calling
  tool can surface a clean error envelope. Existing rows for this
  source are *not* deleted in that case (we do the delete inside the
  same transaction so a flush failure rolls back).
- DB write fails: standard SQLAlchemy error bubbles up; transaction
  rolls back so the project memory stays consistent.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory.chunker import (
    Chunk,
    chunk_cost_engine,
    chunk_design_version,
    chunk_drawing_or_diagram,
    chunk_spec_bundle,
)
from app.memory.embeddings import Embedder, get_embedder
from app.repositories.project_memory import ProjectMemoryRepository

log = logging.getLogger(__name__)


@dataclass
class IndexResult:
    """Summary of one indexing operation."""

    project_id: str
    source_type: str
    source_id: str
    source_version: str
    chunk_count: int
    deleted_count: int
    embedding_model: str
    skipped_reason: Optional[str] = None


# ─────────────────────────────────────────────────────────────────────
# Indexer
# ─────────────────────────────────────────────────────────────────────


class ProjectMemoryIndexer:
    """Stateless indexer — pass-through to chunker + embedder + repo."""

    def __init__(self, embedder: Optional[Embedder] = None) -> None:
        self._embedder = embedder or get_embedder()

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    # ────────────────────────────────────────────────────────────────
    # Generic entry point
    # ────────────────────────────────────────────────────────────────

    async def index_chunks(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        owner_id: str,
        source_type: str,
        source_id: str,
        source_version: str,
        chunks: list[Chunk],
        extra: Optional[dict[str, Any]] = None,
    ) -> IndexResult:
        """Replace any existing chunks for the source with these new ones.

        Lower-level than the per-source helpers below — use when you
        need to feed pre-chunked text in (e.g. from a custom chunker).
        """
        # Delete prior chunks for this exact (source, version).
        deleted = await ProjectMemoryRepository.delete_chunks_for_source(
            session,
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
        )

        if not chunks:
            return IndexResult(
                project_id=project_id,
                source_type=source_type,
                source_id=source_id,
                source_version=source_version,
                chunk_count=0,
                deleted_count=deleted,
                embedding_model=self._embedder.name,
                skipped_reason="no_content",
            )

        contents = [c.content for c in chunks]
        vectors = await self._embedder.embed_many(contents)

        if len(vectors) != len(chunks):
            raise RuntimeError(
                f"Embedder returned {len(vectors)} vectors for "
                f"{len(chunks)} chunks — refusing to insert mismatched rows"
            )

        rows_payload: list[dict[str, Any]] = []
        for c, vec in zip(chunks, vectors):
            payload: dict[str, Any] = {
                "content": c.content,
                "embedding": vec,
                "chunk_index": c.chunk_index,
                "total_chunks": c.total_chunks,
                "token_estimate": c.token_estimate,
            }
            merged_extra = dict(c.extra or {})
            if extra:
                merged_extra = {**merged_extra, **extra}
            payload["extra"] = merged_extra
            rows_payload.append(payload)

        await ProjectMemoryRepository.insert_chunks(
            session,
            project_id=project_id,
            owner_id=owner_id,
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
            chunks=rows_payload,
        )

        return IndexResult(
            project_id=project_id,
            source_type=source_type,
            source_id=source_id,
            source_version=source_version,
            chunk_count=len(chunks),
            deleted_count=deleted,
            embedding_model=self._embedder.name,
        )

    # ────────────────────────────────────────────────────────────────
    # Per-source-type helpers
    # ────────────────────────────────────────────────────────────────

    async def index_design_version(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        owner_id: str,
        version_id: str,
        version: int,
        graph_data: dict[str, Any],
        project_name: str = "",
    ) -> IndexResult:
        version_label = f"v{version}"
        chunks = chunk_design_version(
            graph_data,
            project_name=project_name,
            version_label=version_label,
        )
        return await self.index_chunks(
            session,
            project_id=project_id,
            owner_id=owner_id,
            source_type="design_version",
            source_id=str(version_id),
            source_version=version_label,
            chunks=chunks,
            extra={"version": version, "project_name": project_name},
        )

    async def index_spec_bundle(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        owner_id: str,
        version_id: str,
        version: int,
        bundle: dict[str, Any],
        project_name: str = "",
    ) -> IndexResult:
        chunks = chunk_spec_bundle(bundle, project_name=project_name)
        return await self.index_chunks(
            session,
            project_id=project_id,
            owner_id=owner_id,
            source_type="spec_bundle",
            source_id=str(version_id),
            source_version=f"v{version}",
            chunks=chunks,
            extra={"version": version},
        )

    async def index_cost_engine(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        owner_id: str,
        snapshot_id: str,
        cost_engine: dict[str, Any],
    ) -> IndexResult:
        chunks = chunk_cost_engine(
            cost_engine, pricing_snapshot_id=snapshot_id,
        )
        return await self.index_chunks(
            session,
            project_id=project_id,
            owner_id=owner_id,
            source_type="cost_engine",
            source_id=str(snapshot_id),
            source_version="",
            chunks=chunks,
        )

    async def index_drawing_or_diagram(
        self,
        session: AsyncSession,
        *,
        project_id: str,
        owner_id: str,
        kind: str,                      # plan_view / elevation_view / concept_transparency / ...
        artefact_id: str,
        spec: dict[str, Any],
        title: str = "",
        theme: str = "",
        version: str = "",
    ) -> IndexResult:
        chunks = chunk_drawing_or_diagram(
            spec, kind=kind, title=title, theme=theme,
        )
        # ``source_type`` is the kind itself (plan_view, hierarchy, …)
        # so the search tool can filter on the fine-grained type.
        return await self.index_chunks(
            session,
            project_id=project_id,
            owner_id=owner_id,
            source_type=kind,
            source_id=str(artefact_id),
            source_version=version,
            chunks=chunks,
            extra={"title": title, "theme": theme},
        )
