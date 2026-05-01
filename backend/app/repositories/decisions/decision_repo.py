"""Design-decision repository — append-only project decision log."""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import DesignDecision


class DesignDecisionRepository:
    """Async repo for :class:`DesignDecision`.

    Append-only by convention — the agent records new decisions but
    never amends old ones (a follow-up decision creates a new row
    that supersedes the prior, with the prior referenced under
    ``rejected_alternatives`` if relevant).
    """

    @staticmethod
    async def record(
        session: AsyncSession,
        *,
        project_id: str,
        actor_id: Optional[str],
        title: str,
        summary: str,
        category: str = "general",
        version: int = 0,
        rationale: str = "",
        rejected_alternatives: Optional[list[Any]] = None,
        sources: Optional[list[Any]] = None,
        tags: Optional[list[str]] = None,
        extra: Optional[dict[str, Any]] = None,
        # Stage 11 — reasoning transparency fields. All optional so
        # legacy callers (Stage 8) keep working unchanged.
        reasoning_steps: Optional[list[Any]] = None,
        confidence_score: Optional[float] = None,
        confidence_factors: Optional[list[str]] = None,
        provenance: Optional[dict[str, Any]] = None,
    ) -> DesignDecision:
        row = DesignDecision(
            project_id=project_id,
            actor_id=actor_id,
            version=int(version or 0),
            category=category or "general",
            title=title,
            summary=summary,
            rationale=rationale or "",
            rejected_alternatives=list(rejected_alternatives or []),
            sources=list(sources or []),
            tags=list(tags or []),
            extra=dict(extra or {}),
            reasoning_steps=list(reasoning_steps or []),
            confidence_score=(
                None if confidence_score is None
                else max(0.0, min(1.0, float(confidence_score)))
            ),
            confidence_factors=list(confidence_factors or []),
            provenance=dict(provenance or {}),
        )
        session.add(row)
        await session.flush()
        return row

    @staticmethod
    async def get_by_id(
        session: AsyncSession,
        *,
        decision_id: str,
    ) -> Optional[DesignDecision]:
        result = await session.execute(
            select(DesignDecision).where(DesignDecision.id == decision_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_for_project(
        session: AsyncSession,
        *,
        project_id: str,
        category: Optional[str] = None,
        version: Optional[int] = None,
        limit: int = 50,
    ) -> list[DesignDecision]:
        stmt = select(DesignDecision).where(
            DesignDecision.project_id == project_id,
        )
        if category is not None:
            stmt = stmt.where(DesignDecision.category == category)
        if version is not None:
            stmt = stmt.where(DesignDecision.version == int(version))
        stmt = stmt.order_by(DesignDecision.created_at.desc()).limit(
            max(1, min(int(limit), 500))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def search_for_project(
        session: AsyncSession,
        *,
        project_id: str,
        query: str,
        limit: int = 20,
    ) -> list[DesignDecision]:
        """Cheap LIKE-based search across title + summary + rationale.

        Stage 8 ships pure-Postgres LIKE; semantic search across
        decisions could be wired into ``project_memory_chunks`` in
        a future stage.
        """
        query = (query or "").strip()
        if not query:
            return []
        like = f"%{query}%"
        stmt = (
            select(DesignDecision)
            .where(
                DesignDecision.project_id == project_id,
                or_(
                    DesignDecision.title.ilike(like),
                    DesignDecision.summary.ilike(like),
                    DesignDecision.rationale.ilike(like),
                ),
            )
            .order_by(DesignDecision.created_at.desc())
            .limit(max(1, min(int(limit), 100)))
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    async def count_for_project(
        session: AsyncSession,
        *,
        project_id: str,
    ) -> int:
        result = await session.execute(
            select(func.count(DesignDecision.id)).where(
                DesignDecision.project_id == project_id,
            )
        )
        return int(result.scalar_one() or 0)
