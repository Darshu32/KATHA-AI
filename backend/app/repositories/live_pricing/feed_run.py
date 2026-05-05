"""Repository for ``feed_runs`` — execution log."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.database import _uuid
from app.models.feeds import FeedRun
from app.repositories.live_pricing._serialize import feed_run_to_dict


class FeedRunRepository:
    """Append-only repository — no soft-delete, no versioning."""

    def __init__(self, session) -> None:
        self.session = session

    async def begin_run(
        self,
        *,
        feed_source: str,
        trigger: str = "beat",
        request_id: Optional[str] = None,
        actor_id: Optional[str] = None,
    ) -> dict[str, Any]:
        run = FeedRun(
            id=_uuid(),
            feed_source=feed_source,
            trigger=trigger,
            started_at=datetime.now(timezone.utc),
            status="failure",  # promoted on completion; safe default for crashes
            request_id=request_id,
            actor_id=actor_id,
        )
        self.session.add(run)
        await self.session.flush()
        return feed_run_to_dict(run)

    async def complete_run(
        self,
        *,
        run_id: str,
        status: str,
        quotes_fetched: int = 0,
        quotes_inserted: int = 0,
        quotes_skipped: int = 0,
        anomalies_detected: int = 0,
        error_message: Optional[str] = None,
        error_payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if status not in {"success", "partial", "failure", "skipped"}:
            raise ValueError(f"Invalid status: {status!r}")

        row = await self.session.get(FeedRun, run_id)
        if row is None:
            raise LookupError(f"FeedRun {run_id!r} not found")

        completed = datetime.now(timezone.utc)
        row.completed_at = completed
        if row.started_at:
            delta = completed - row.started_at
            row.duration_ms = int(delta.total_seconds() * 1000)
        row.status = status
        row.quotes_fetched = quotes_fetched
        row.quotes_inserted = quotes_inserted
        row.quotes_skipped = quotes_skipped
        row.anomalies_detected = anomalies_detected
        if error_message:
            row.error_message = error_message
        if error_payload:
            row.error_payload = error_payload
        await self.session.flush()
        return feed_run_to_dict(row)

    async def latest_per_feed(self) -> list[dict[str, Any]]:
        """Newest run per feed_source — powers the admin dashboard."""
        from sqlalchemy import func

        latest = (
            select(
                FeedRun.feed_source,
                func.max(FeedRun.started_at).label("max_started"),
            )
            .group_by(FeedRun.feed_source)
            .subquery()
        )
        stmt = (
            select(FeedRun)
            .join(
                latest,
                (FeedRun.feed_source == latest.c.feed_source)
                & (FeedRun.started_at == latest.c.max_started),
            )
            .order_by(FeedRun.feed_source)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [feed_run_to_dict(r) for r in rows]

    async def history(
        self,
        *,
        feed_source: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = select(FeedRun).order_by(FeedRun.started_at.desc()).limit(limit)
        if feed_source:
            stmt = stmt.where(FeedRun.feed_source == feed_source)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [feed_run_to_dict(r) for r in rows]
