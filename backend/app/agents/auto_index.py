"""Stage 5C/5D — best-effort auto-indexing for the generation pipeline.

The Stage 4G pipeline tools (``generate_initial_design``,
``apply_theme``, ``edit_design_object``) all persist a new
:class:`DesignGraphVersion`. Without auto-indexing, the agent has
to call ``index_project_artefact`` separately to make the version
semantically retrievable. This module closes the gap.

Two modes
---------
- **Inline** (Stage 5C, default). The indexer runs in the same async
  task as the pipeline tool. Generation waits for the embedding +
  chunk insert (~500 ms–2 s with OpenAI; near-instant with the
  stub). Failures surface as ``indexed=False`` flags on the parent
  reply.
- **Async** (Stage 5D, opt-in via ``settings.async_indexing_enabled``).
  The indexer is dispatched as a Celery task on the ``ingestion``
  queue. The parent reply returns immediately with
  ``index_skipped_reason="queued"`` and a ``index_task_id`` the
  client can poll. Worker writes chunks behind the scenes.

Why "best effort"
-----------------
Indexing requires:

- An embedding round-trip (OpenAI by default — could be slow or down).
- One DELETE + N INSERTs into ``project_memory_chunks``.

If either step fails we don't want to lose the user-facing design
generation that just succeeded. So this module catches **every**
exception from the indexer (inline mode) or broker (async mode) and
surfaces them as a structured result the calling tool can attach to
its reply.

What this module is not
-----------------------
- It does **not** auto-index spec bundles, drawings, diagrams, or
  cost runs. Those artefacts only exist in the agent's reply (no DB
  row), so an explicit ``index_project_artefact`` call is the right
  surface.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.memory import IndexResult, ProjectMemoryIndexer

log = logging.getLogger(__name__)


@dataclass
class AutoIndexResult:
    """Outcome of a best-effort indexing attempt.

    ``indexed`` is True iff the indexer returned a result *with*
    chunks. A successful no-op (the source happened to chunk to zero
    text) is still ``indexed=False`` with a ``skipped_reason`` —
    callers can surface this distinction without re-checking
    ``chunk_count``.

    For Stage 5D async mode, ``task_id`` carries the Celery task id
    when ``skipped_reason="queued"``. ``None`` in inline mode.
    """

    indexed: bool
    chunk_count: int
    deleted_count: int
    skipped_reason: Optional[str]
    embedder: Optional[str]
    error: Optional[str]
    task_id: Optional[str] = None

    @classmethod
    def from_index_result(cls, result: IndexResult) -> "AutoIndexResult":
        return cls(
            indexed=result.chunk_count > 0,
            chunk_count=result.chunk_count,
            deleted_count=result.deleted_count,
            skipped_reason=result.skipped_reason,
            embedder=result.embedding_model,
            error=None,
            task_id=None,
        )

    @classmethod
    def from_error(cls, exc: BaseException) -> "AutoIndexResult":
        return cls(
            indexed=False,
            chunk_count=0,
            deleted_count=0,
            skipped_reason="error",
            embedder=None,
            error=f"{type(exc).__name__}: {exc}",
            task_id=None,
        )

    @classmethod
    def from_queued(cls, task_id: Optional[str]) -> "AutoIndexResult":
        """Stage 5D — async dispatch outcome."""
        return cls(
            indexed=False,
            chunk_count=0,
            deleted_count=0,
            skipped_reason="queued" if task_id else "dispatch_failed",
            embedder=None,
            error=None if task_id else "broker dispatch returned no task id",
            task_id=task_id,
        )


# ─────────────────────────────────────────────────────────────────────
# Auto-indexers (one per artefact kind)
# ─────────────────────────────────────────────────────────────────────


async def auto_index_design_version(
    session: AsyncSession,
    *,
    project_id: Optional[str],
    owner_id: Optional[str],
    version_id: Optional[str],
    version: int,
    graph_data: dict[str, Any],
    project_name: str = "",
    indexer: Optional[ProjectMemoryIndexer] = None,
    async_mode: Optional[bool] = None,
) -> AutoIndexResult:
    """Index a freshly-saved design version into project memory.

    Returns an :class:`AutoIndexResult` describing success or the
    reason indexing was skipped. Never raises — callers can attach
    the result to their reply unconditionally.

    Mode selection
    --------------
    - ``async_mode=None`` (default): consult ``settings.async_indexing_enabled``.
    - ``async_mode=True``: dispatch to Celery, return ``"queued"`` immediately.
    - ``async_mode=False``: run inline, even if the global flag is on.

    Skipped reasons
    ---------------
    - ``"no_project_id"`` / ``"no_owner_id"`` / ``"no_version_id"``:
      caller didn't supply enough scope. Indexer doesn't try.
    - ``"no_content"``: the chunker produced zero chunks (empty graph).
    - ``"error"``: an exception was raised — see the ``error`` field
      for the type + message.
    - ``"queued"``: async dispatch succeeded; ``task_id`` is the Celery id.
    - ``"dispatch_failed"``: async mode requested but the broker
      rejected the dispatch (Redis down, etc.).
    """
    if not project_id:
        return AutoIndexResult(
            indexed=False, chunk_count=0, deleted_count=0,
            skipped_reason="no_project_id", embedder=None, error=None,
        )
    if not owner_id:
        return AutoIndexResult(
            indexed=False, chunk_count=0, deleted_count=0,
            skipped_reason="no_owner_id", embedder=None, error=None,
        )
    if not version_id:
        return AutoIndexResult(
            indexed=False, chunk_count=0, deleted_count=0,
            skipped_reason="no_version_id", embedder=None, error=None,
        )

    # Resolve the effective async mode.
    if async_mode is None:
        try:
            from app.config import get_settings
            async_mode = bool(get_settings().async_indexing_enabled)
        except Exception:  # noqa: BLE001 — settings should never fail, but defend
            async_mode = False

    # ── Async path ──────────────────────────────────────────────────
    if async_mode:
        # Local import so the inline path doesn't take a Celery dep
        # (and so test environments without Redis can still import
        # this module).
        try:
            from app.workers.memory_tasks import dispatch_index_design_version
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "Async indexing requested but Celery import failed; "
                "falling back to inline path: %s", exc,
            )
            async_mode = False
        else:
            task_id = dispatch_index_design_version(
                project_id=project_id,
                owner_id=owner_id,
                version_id=version_id,
                version=version,
                graph_data=graph_data or {},
                project_name=project_name,
            )
            return AutoIndexResult.from_queued(task_id)

    # ── Inline path ─────────────────────────────────────────────────
    indexer = indexer or ProjectMemoryIndexer()

    try:
        result = await indexer.index_design_version(
            session,
            project_id=project_id,
            owner_id=owner_id,
            version_id=version_id,
            version=version,
            graph_data=graph_data or {},
            project_name=project_name,
        )
    except Exception as exc:  # noqa: BLE001 — best-effort, log + swallow
        log.warning(
            "auto_index_design_version failed for project=%s version_id=%s: %s",
            project_id, version_id, exc,
            exc_info=True,
        )
        return AutoIndexResult.from_error(exc)

    return AutoIndexResult.from_index_result(result)
