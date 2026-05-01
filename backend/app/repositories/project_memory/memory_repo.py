"""Project memory repository — read/write to ``project_memory_chunks``.

The only module that touches the table directly. The indexer + retriever
call into here; everything else uses those higher-level surfaces.

All methods take an :class:`AsyncSession` from the caller and flush
without committing — the calling tool / route owns the transaction.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import ProjectMemoryChunk

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Hits — what search returns
# ─────────────────────────────────────────────────────────────────────


# A search hit is just a (chunk, distance) tuple — keep this lightweight
# and let the retriever wrap into a richer dataclass.
SearchRow = tuple[ProjectMemoryChunk, float]


# ─────────────────────────────────────────────────────────────────────
# Repository
# ─────────────────────────────────────────────────────────────────────


class ProjectMemoryRepository:
    """Async repo for :class:`ProjectMemoryChunk`."""

    @staticmethod
    async def insert_chunks(
        session: AsyncSession,
        *,
        project_id: str,
        owner_id: str,
        source_type: str,
        source_id: str,
        source_version: str,
        chunks: list[dict[str, Any]],
    ) -> list[ProjectMemoryChunk]:
        """Insert one or more chunks for a single source.

        Each ``chunks[i]`` is a dict with keys:

        - ``content``: str — the indexed text
        - ``embedding``: list[float] — the 1536-dim vector
        - ``chunk_index`` / ``total_chunks``: ints
        - ``token_estimate``: int
        - ``extra``: dict (optional)

        The repo does **not** delete existing chunks for the same
        logical source — that's the indexer's responsibility (it's
        the layer that knows about idempotency policy). Use
        :meth:`delete_chunks_for_source` if you want replace semantics.
        """
        rows: list[ProjectMemoryChunk] = []
        for c in chunks:
            row = ProjectMemoryChunk(
                project_id=project_id,
                owner_id=owner_id,
                source_type=source_type,
                source_id=source_id,
                source_version=source_version,
                chunk_index=int(c.get("chunk_index") or 0),
                total_chunks=int(c.get("total_chunks") or 1),
                content=str(c.get("content") or ""),
                token_estimate=int(c.get("token_estimate") or 0),
                embedding=list(c.get("embedding") or []),
                extra=dict(c.get("extra") or {}),
            )
            session.add(row)
            rows.append(row)
        await session.flush()
        return rows

    @staticmethod
    async def delete_chunks_for_source(
        session: AsyncSession,
        *,
        project_id: str,
        source_type: str,
        source_id: str,
        source_version: Optional[str] = None,
    ) -> int:
        """Remove every chunk for a given logical source.

        When ``source_version`` is None, every version of the source
        is wiped — useful for "re-index this design from scratch"
        flows. When supplied, only that specific version's chunks
        are removed.

        Returns the number of rows deleted.
        """
        stmt = delete(ProjectMemoryChunk).where(
            ProjectMemoryChunk.project_id == project_id,
            ProjectMemoryChunk.source_type == source_type,
            ProjectMemoryChunk.source_id == source_id,
        )
        if source_version is not None:
            stmt = stmt.where(ProjectMemoryChunk.source_version == source_version)
        result = await session.execute(stmt)
        await session.flush()
        return int(result.rowcount or 0)

    @staticmethod
    async def count_for_project(
        session: AsyncSession,
        *,
        project_id: str,
    ) -> int:
        """Total chunks recorded for a project."""
        from sqlalchemy import func

        result = await session.execute(
            select(func.count(ProjectMemoryChunk.id)).where(
                ProjectMemoryChunk.project_id == project_id,
            )
        )
        return int(result.scalar_one() or 0)

    @staticmethod
    async def prune_old_design_versions(
        session: AsyncSession,
        *,
        project_id: str,
        keep_latest: int,
    ) -> int:
        """Drop ``design_version`` chunks for older versions of a project.

        ``keep_latest`` is the number of most-recent design versions
        whose chunks survive — older ones are deleted. We sort by
        the integer parsed out of ``source_version`` ("v3" → 3) so
        the eviction follows the actual generation order rather than
        DB insert order.

        Returns the number of rows deleted.

        Why design_version only
        -----------------------
        Spec bundles, cost runs, drawings, and diagrams are
        agent-driven artefacts whose ``source_version`` semantics
        differ. Pruning those would require a per-source-type
        retention policy. Stage 5D scopes to the deterministic
        case — design versions tracked by an integer counter.

        ``keep_latest <= 0`` is a no-op (returns 0); we never
        truncate the entire project.
        """
        keep_latest = int(keep_latest)
        if keep_latest <= 0:
            return 0

        # Find the distinct (source_id, source_version) pairs for
        # design_version chunks in this project, ordered newest-first
        # by the integer version. Anything past index ``keep_latest``
        # gets pruned.
        rows = await session.execute(
            select(
                ProjectMemoryChunk.source_id,
                ProjectMemoryChunk.source_version,
            )
            .where(
                ProjectMemoryChunk.project_id == project_id,
                ProjectMemoryChunk.source_type == "design_version",
            )
            .distinct()
        )
        pairs = list(rows.all())

        def _version_int(label: str) -> int:
            """Parse 'v3' → 3 for sort. Falls back to -1 on weird inputs."""
            label = (label or "").strip().lower()
            if label.startswith("v"):
                label = label[1:]
            try:
                return int(label)
            except ValueError:
                return -1

        # Newest first — pairs[i].version_int >= pairs[i+1].version_int.
        sorted_pairs = sorted(
            pairs, key=lambda p: _version_int(p[1]), reverse=True,
        )
        to_drop = sorted_pairs[keep_latest:]
        if not to_drop:
            return 0

        # Delete chunks for the to-drop (source_id, source_version) tuples.
        # We do one DELETE per pair — small N and the index covers it.
        total_deleted = 0
        for source_id, source_version in to_drop:
            res = await session.execute(
                delete(ProjectMemoryChunk).where(
                    ProjectMemoryChunk.project_id == project_id,
                    ProjectMemoryChunk.source_type == "design_version",
                    ProjectMemoryChunk.source_id == source_id,
                    ProjectMemoryChunk.source_version == source_version,
                )
            )
            total_deleted += int(res.rowcount or 0)
        await session.flush()
        return total_deleted

    @staticmethod
    async def list_for_source(
        session: AsyncSession,
        *,
        project_id: str,
        source_type: str,
        source_id: str,
        source_version: Optional[str] = None,
    ) -> list[ProjectMemoryChunk]:
        """List every chunk for a source, ordered by chunk_index."""
        stmt = (
            select(ProjectMemoryChunk)
            .where(
                ProjectMemoryChunk.project_id == project_id,
                ProjectMemoryChunk.source_type == source_type,
                ProjectMemoryChunk.source_id == source_id,
            )
            .order_by(ProjectMemoryChunk.chunk_index.asc())
        )
        if source_version is not None:
            stmt = stmt.where(ProjectMemoryChunk.source_version == source_version)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    # ────────────────────────────────────────────────────────────────
    # Search
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    async def search(
        session: AsyncSession,
        *,
        project_id: str,
        query_embedding: list[float],
        owner_id: Optional[str] = None,
        source_type: Optional[str] = None,
        top_k: int = 5,
    ) -> list[SearchRow]:
        """Cosine-similarity search across a project's chunks.

        Returns up to ``top_k`` rows sorted by *increasing* cosine
        distance (smaller = closer). Pair the row with its distance
        so the retriever can compute a similarity score for the LLM.

        ``owner_id`` is recommended when called from a request scope
        — adds a cheap btree filter and prevents accidental cross-
        owner leakage if the project FK is ever stale.
        """
        if not query_embedding:
            return []

        # ``Vector`` exposes ``cosine_distance`` on the column. The
        # operator is ``<=>`` in pgvector; SQLAlchemy renders it for us.
        col = ProjectMemoryChunk.embedding
        try:
            distance = col.cosine_distance(query_embedding)  # type: ignore[attr-defined]
        except AttributeError:
            # Fallback when pgvector isn't installed — surface a clear
            # error rather than silently returning nothing.
            raise RuntimeError(
                "pgvector is not installed — cosine_distance unavailable. "
                "Run `pip install pgvector` and `CREATE EXTENSION vector`."
            )

        stmt = (
            select(ProjectMemoryChunk, distance.label("distance"))
            .where(ProjectMemoryChunk.project_id == project_id)
            .order_by(distance.asc())
            .limit(max(1, min(int(top_k), 50)))
        )
        if owner_id is not None:
            stmt = stmt.where(ProjectMemoryChunk.owner_id == owner_id)
        if source_type is not None:
            stmt = stmt.where(ProjectMemoryChunk.source_type == source_type)

        result = await session.execute(stmt)
        return [(row[0], float(row[1])) for row in result.all()]
