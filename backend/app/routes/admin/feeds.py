"""Admin endpoints for Stage 12 live data feeds.

Surface for ops + senior designers:

- ``GET  /admin/feeds``                 — dashboard payload (per-feed
  status, last run, anomaly threshold, unacknowledged alerts).
- ``GET  /admin/feeds/{source}/quotes`` — current active quotes.
- ``GET  /admin/feeds/{source}/history``— per-feed run history.
- ``POST /admin/feeds/{source}/refresh``— manual trigger.
- ``GET  /admin/feeds/alerts``          — recent + unacknowledged.
- ``POST /admin/feeds/alerts/{id}/ack`` — mark an alert handled.

Auth uses the existing :func:`get_current_user` dependency. Manual
refresh runs synchronously (it's a single HTTP request — the user
is waiting for the result) using the same orchestrator the Celery
beat job uses.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.feeds.registry import get_registry
from app.feeds.service import feed_status_summary, run_feed
from app.middleware import get_current_user
from app.models.orm import User
from app.observability.error_codes import ErrorCode, http_status_for
from app.observability.error_envelope import build_envelope
from app.observability.request_id import get_request_id
from app.repositories.live_pricing import (
    FeedRunRepository,
    LivePriceQuoteRepository,
    PriceAnomalyAlertRepository,
)

router = APIRouter(prefix="/admin/feeds", tags=["admin", "feeds"])


def _not_found(message: str, code: ErrorCode = ErrorCode.FEED_NOT_FOUND):
    return HTTPException(
        status_code=http_status_for(code),
        detail=build_envelope(
            code=code,
            message=message,
            request_id=get_request_id(),
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────


@router.get("")
async def feeds_dashboard(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    """Top-level dashboard payload — what the ops UI lands on."""
    return await feed_status_summary(db)


# ─────────────────────────────────────────────────────────────────────
# Per-feed views
# ─────────────────────────────────────────────────────────────────────


@router.get("/{source}/quotes")
async def list_quotes(
    source: str,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    if get_registry().get(source) is None:
        raise _not_found(f"unknown feed source: {source!r}")
    repo = LivePriceQuoteRepository(db)
    rows = await repo.list_active(feed_source=source)
    return {"feed_source": source, "quotes": rows, "count": len(rows)}


@router.get("/{source}/quotes/{commodity_key}/history")
async def quote_history(
    source: str,
    commodity_key: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    if get_registry().get(source) is None:
        raise _not_found(f"unknown feed source: {source!r}")
    repo = LivePriceQuoteRepository(db)
    versions = await repo.history(
        feed_source=source,
        commodity_key=commodity_key,
        limit=limit,
    )
    if not versions:
        raise _not_found(
            f"no history for {source}/{commodity_key}",
        )
    return {
        "feed_source": source,
        "commodity_key": commodity_key,
        "versions": versions,
    }


@router.get("/{source}/runs")
async def feed_runs(
    source: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    if get_registry().get(source) is None:
        raise _not_found(f"unknown feed source: {source!r}")
    repo = FeedRunRepository(db)
    runs = await repo.history(feed_source=source, limit=limit)
    return {"feed_source": source, "runs": runs}


class _RefreshBody(BaseModel):
    force: bool = Field(
        default=False,
        description=(
            "Override the per-feed enable flag for this run. The master "
            "live_feeds_enabled switch is NOT overridable."
        ),
    )


@router.post("/{source}/refresh", status_code=status.HTTP_200_OK)
async def refresh_feed(
    source: str,
    payload: _RefreshBody = Body(default_factory=_RefreshBody),
    user: User = Depends(get_current_user),
) -> dict:
    if get_registry().get(source) is None:
        raise _not_found(f"unknown feed source: {source!r}")
    try:
        run = await run_feed(
            source,
            trigger="manual",
            actor_id=user.id,
            force=payload.force,
        )
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    return {"feed_source": source, "run": run}


# ─────────────────────────────────────────────────────────────────────
# Anomaly alerts
# ─────────────────────────────────────────────────────────────────────


@router.get("/alerts")
async def list_alerts(
    feed_source: Optional[str] = Query(default=None),
    only_unacknowledged: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict:
    repo = PriceAnomalyAlertRepository(db)
    if only_unacknowledged:
        rows = await repo.list_unacknowledged(feed_source=feed_source, limit=limit)
    else:
        rows = await repo.list_recent(feed_source=feed_source, limit=limit)
    return {"alerts": rows, "count": len(rows)}


@router.post("/alerts/{alert_id}/ack", status_code=status.HTTP_200_OK)
async def acknowledge_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    repo = PriceAnomalyAlertRepository(db)
    try:
        row = await repo.acknowledge(alert_id=alert_id, actor_id=user.id)
    except LookupError as exc:
        raise _not_found(str(exc)) from exc
    return {"alert": row}
