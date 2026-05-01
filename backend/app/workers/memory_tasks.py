"""Stage 5D — Celery tasks for project memory.

Indexing a design version takes one OpenAI embedding round-trip
plus one DELETE + N INSERTs. With ``async_indexing_enabled=True``
the pipeline tools dispatch this work to Celery so generation
returns immediately. The worker picks the job up off the
``ingestion`` queue and writes chunks behind the scenes.

Why a separate module from :mod:`app.workers.tasks`
---------------------------------------------------
Tasks here all share the same shape — they open a fresh DB
session, instantiate the indexer, write chunks, commit. Keeping
them grouped makes the surface easy to scan and the queue config
in :mod:`app.workers.celery_app` self-documenting.

Task contract
-------------
- Tasks are *idempotent* — re-running the same task with the same
  args replaces the prior chunks (the indexer's delete-then-insert
  guarantees this).
- Tasks own their DB transaction (open session → flush → commit)
  because they run in a separate process from the request that
  dispatched them.
- Failures are retried by Celery's default policy (3 retries with
  exponential backoff). Persistent failures get logged + dropped —
  the user-facing generation has long since succeeded.
- Inputs are JSON-serialisable (Celery's default ``json`` codec),
  so we pass plain dicts / strings / ints — no dataclasses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine inside a sync Celery task body."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(
    bind=True,
    name="app.workers.memory_tasks.index_design_version_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def index_design_version_task(
    self,
    *,
    project_id: str,
    owner_id: str,
    version_id: str,
    version: int,
    graph_data: dict[str, Any],
    project_name: str = "",
) -> dict[str, Any]:
    """Background indexer for a single design version.

    Receives the full ``graph_data`` rather than re-fetching by
    ``version_id`` — the dispatching tool already has the dict in
    memory, and this avoids any "task picked up before parent
    transaction committed" race.

    Returns a JSON-serialisable summary the caller can inspect via
    Celery's result backend (Redis db 2). Production usage rarely
    inspects results — the result is mostly for debugging.
    """
    log.info(
        "memory_tasks.index_design_version_task start: project=%s version_id=%s version=%s",
        project_id, version_id, version,
    )

    async def _run() -> dict[str, Any]:
        # Local imports keep Celery's import-time fast — these
        # transitively pull SQLAlchemy / OpenAI clients.
        from app.database import async_session_factory
        from app.memory import ProjectMemoryIndexer

        async with async_session_factory() as db:
            try:
                indexer = ProjectMemoryIndexer()
                result = await indexer.index_design_version(
                    db,
                    project_id=project_id,
                    owner_id=owner_id,
                    version_id=version_id,
                    version=version,
                    graph_data=graph_data or {},
                    project_name=project_name,
                )
                await db.commit()
                return {
                    "ok": True,
                    "chunk_count": result.chunk_count,
                    "deleted_count": result.deleted_count,
                    "skipped_reason": result.skipped_reason,
                    "embedder": result.embedding_model,
                }
            except Exception:
                await db.rollback()
                raise

    try:
        return _run_async(_run())
    except Exception as exc:
        # Celery will retry up to ``max_retries`` times via the
        # ``autoretry_for`` decorator above. We log + re-raise so
        # the retry kicks in. A persistent failure is dropped after
        # the retries are exhausted; the user-facing generation
        # already returned ok=True so the only impact is stale
        # memory until the agent re-indexes (or the user re-runs).
        log.exception(
            "memory_tasks.index_design_version_task failed for "
            "project=%s version_id=%s — will retry: %s",
            project_id, version_id, exc,
        )
        raise


# Re-export for autodiscovery — the @task decorator already
# registers it with celery_app, but the explicit reference keeps
# linters happy when this module is imported only for its name.
__all__ = ["index_design_version_task"]


def dispatch_index_design_version(
    *,
    project_id: str,
    owner_id: str,
    version_id: str,
    version: int,
    graph_data: dict[str, Any],
    project_name: str = "",
    countdown_seconds: int = 1,
) -> Optional[str]:
    """Send an indexing job to Celery and return the task id.

    ``countdown_seconds`` defaults to 1 so the broker has a beat to
    let the parent request commit before the worker picks up the
    job. Set to 0 for tests using ``task_always_eager``.

    Returns ``None`` when dispatch itself fails (broker down) so
    the caller can surface a graceful "failed to queue" state
    rather than crashing.
    """
    try:
        async_result = index_design_version_task.apply_async(
            kwargs={
                "project_id": project_id,
                "owner_id": owner_id,
                "version_id": version_id,
                "version": version,
                "graph_data": graph_data,
                "project_name": project_name,
            },
            countdown=max(0, int(countdown_seconds)),
        )
    except Exception as exc:  # noqa: BLE001 — broker outages are non-fatal
        log.warning(
            "Failed to dispatch index_design_version_task for "
            "project=%s version=%s: %s",
            project_id, version_id, exc,
        )
        return None

    return str(getattr(async_result, "id", "") or "") or None
