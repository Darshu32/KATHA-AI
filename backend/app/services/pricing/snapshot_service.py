"""Capture + replay of pricing knowledge snapshots.

Stage 1's correctness guarantee:

    *An estimate generated today must reproduce the same numbers
    forever, even after a price update.*

This module makes that true. When a cost-engine run completes we
``record_snapshot()`` the entire pricing knowledge dict it consumed.
Re-running the cost-engine for the same target later passes the
captured snapshot through ``load_snapshot()`` instead of rebuilding
from live DB rows.

Snapshots are also the **provenance receipt** for Stage 11
transparency: every cited price has a row id + version + source tag
recorded in ``snapshot_data["source_versions"]``.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.observability.request_id import get_request_id
from app.repositories.pricing import PricingSnapshotRepository


# ─────────────────────────────────────────────────────────────────────
# Capture
# ─────────────────────────────────────────────────────────────────────


async def record_snapshot(
    session: AsyncSession,
    *,
    knowledge: dict[str, Any],
    target_type: str = "cost_engine",
    target_id: Optional[str] = None,
    project_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    actor_kind: str = "system",
) -> dict[str, Any]:
    """Persist a pricing knowledge dict so it can be replayed later.

    Returns the serialised snapshot row including ``id``. Caller is
    expected to attach this id to their own artefact (estimate row,
    cost-engine response, etc).

    The session is **not** committed here — caller controls the
    transaction boundary.
    """
    project = knowledge.get("project") or {}
    source_versions = knowledge.get("source_versions") or {}

    repo = PricingSnapshotRepository(session)
    return await repo.create(
        target_type=target_type,
        target_id=target_id,
        snapshot_data=knowledge,
        source_versions=source_versions,
        project_id=project_id,
        city=project.get("city"),
        market_segment=project.get("market_segment"),
        actor_id=actor_id,
        actor_kind=actor_kind,
        request_id=get_request_id(),
    )


# ─────────────────────────────────────────────────────────────────────
# Replay
# ─────────────────────────────────────────────────────────────────────


async def load_snapshot(
    session: AsyncSession,
    snapshot_id: str,
) -> Optional[dict[str, Any]]:
    """Return the captured pricing knowledge dict, or ``None`` if missing.

    The returned dict is identical to what
    :func:`app.services.pricing.knowledge_service.build_pricing_knowledge`
    produced at capture time. The cost engine should use the snapshot
    verbatim when reproducing an old estimate; do *not* re-fetch from
    live tables, that defeats the point.
    """
    repo = PricingSnapshotRepository(session)
    row = await repo.get(snapshot_id)
    if row is None:
        return None
    return row["snapshot_data"]
