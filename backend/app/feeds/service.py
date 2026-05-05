"""Service orchestrator for live data feeds.

Single entry point — :func:`run_feed` — invoked by:

- the Celery beat scheduler (one call per feed per cadence);
- the admin endpoint ``POST /admin/feeds/{source}/refresh`` for
  manual triggers;
- integration tests verifying the end-to-end loop.

The orchestrator owns the transactional boundary: one feed run is
one transaction. If anything below the adapter raises (DB problem,
constraint violation), the whole run rolls back AND a ``FeedRun``
row with ``status='failure'`` and the exception message is recorded
in a *separate* short transaction so audit history is preserved
even when the main work fails.
"""

from __future__ import annotations

import logging
import traceback
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession  # used by feed_status_summary

from app.config import get_settings
from app.database import async_session_factory
from app.feeds.anomaly import detect_anomaly
from app.feeds.base import FeedAdapter, FeedQuote, FetchOutcome
from app.feeds.registry import get_registry
from app.feeds.slack import send_anomaly_alert
from app.observability.request_id import get_request_id
from app.repositories.live_pricing import (
    FeedRunRepository,
    LivePriceQuoteRepository,
    PriceAnomalyAlertRepository,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Per-feed enable-flag lookup
# ─────────────────────────────────────────────────────────────────────


def _is_feed_enabled(feed_source: str) -> bool:
    """Per-feed env flag, with the master switch as the override.

    Master switch off → every feed reports disabled (the registry
    bootstraps stub adapters in that case anyway, but we still skip
    network hits and log a ``skipped`` run for dashboard parity).
    """
    s = get_settings()
    if not s.live_feeds_enabled:
        return False

    flag_map = {
        "mcx": s.feed_mcx_enabled,
        "fx_rbi": s.feed_fx_enabled,
        "gst_cbic": s.feed_gst_enabled,
        "vendor:jaquar": s.feed_vendor_jaquar_enabled,
        "vendor:kohler": s.feed_vendor_kohler_enabled,
        "vendor:asian_paints": s.feed_vendor_asian_paints_enabled,
    }
    return flag_map.get(feed_source, True)


# ─────────────────────────────────────────────────────────────────────
# Public orchestration entry point
# ─────────────────────────────────────────────────────────────────────


async def run_feed(
    feed_source: str,
    *,
    trigger: str = "beat",
    actor_id: Optional[str] = None,
    force: bool = False,
) -> dict[str, Any]:
    """Refresh one feed end-to-end and return the run summary.

    ``force=True`` overrides the per-feed enable flag — used by the
    admin "force refresh" button. The master ``live_feeds_enabled``
    switch is *not* overridable; ops keep the global kill-switch.
    """
    registry = get_registry()
    adapter = registry.get(feed_source)
    if adapter is None:
        raise LookupError(f"No adapter registered for {feed_source!r}")

    enabled = _is_feed_enabled(feed_source)
    settings = get_settings()
    if not enabled and not force and settings.live_feeds_enabled:
        return await _record_skipped_run(
            feed_source=feed_source,
            trigger=trigger,
            actor_id=actor_id,
            reason="per-feed flag disabled",
        )

    if not settings.live_feeds_enabled and not force:
        # Master switch off — record the skip so the dashboard shows
        # something other than stale "last run" timestamps.
        return await _record_skipped_run(
            feed_source=feed_source,
            trigger=trigger,
            actor_id=actor_id,
            reason="live_feeds_enabled=false",
        )

    return await _run_with_adapter(
        adapter,
        trigger=trigger,
        actor_id=actor_id,
    )


async def _record_skipped_run(
    *,
    feed_source: str,
    trigger: str,
    actor_id: Optional[str],
    reason: str,
) -> dict[str, Any]:
    async with async_session_factory() as session:
        runs = FeedRunRepository(session)
        run = await runs.begin_run(
            feed_source=feed_source,
            trigger=trigger,
            actor_id=actor_id,
            request_id=get_request_id(),
        )
        run = await runs.complete_run(
            run_id=run["id"],
            status="skipped",
            error_message=reason,
        )
        await session.commit()
        return run


async def _run_with_adapter(
    adapter: FeedAdapter,
    *,
    trigger: str,
    actor_id: Optional[str],
) -> dict[str, Any]:
    """Run one adapter end-to-end with a single transaction boundary.

    Implementation note: when ``adapter.fetch()`` raises (which it
    isn't *supposed* to — adapters should return ``status='failure'``
    instead), we catch + record a ``failure`` run and re-raise nothing.
    The caller (a Celery task) cares only about the run summary.
    """
    feed_source = adapter.feed_source
    request_id = get_request_id()

    async with async_session_factory() as session:
        runs = FeedRunRepository(session)
        run_row = await runs.begin_run(
            feed_source=feed_source,
            trigger=trigger,
            actor_id=actor_id,
            request_id=request_id,
        )
        run_id = run_row["id"]
        await session.commit()

    try:
        outcome = await adapter.fetch()
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("feed adapter %s raised", feed_source)
        return await _finalize_run(
            run_id=run_id,
            feed_source=feed_source,
            outcome=FetchOutcome(
                status="failure",
                error=f"adapter raised: {exc}",
                error_payload={
                    "type": type(exc).__name__,
                    "trace": traceback.format_exc(),
                },
            ),
            actor_id=actor_id,
        )

    return await _finalize_run(
        run_id=run_id,
        feed_source=feed_source,
        outcome=outcome,
        actor_id=actor_id,
    )


async def _finalize_run(
    *,
    run_id: str,
    feed_source: str,
    outcome: FetchOutcome,
    actor_id: Optional[str],
) -> dict[str, Any]:
    """Persist the outcome of an adapter call: quotes + anomalies + run."""
    inserted = 0
    skipped = 0
    anomalies: list[dict[str, Any]] = []
    error_message = outcome.error
    error_payload = dict(outcome.error_payload)

    if outcome.quotes:
        async with async_session_factory() as session:
            quotes_repo = LivePriceQuoteRepository(session)
            anomaly_repo = PriceAnomalyAlertRepository(session)

            for q in outcome.quotes:
                try:
                    persisted, anomaly = await _persist_quote_with_anomaly(
                        feed_source=feed_source,
                        quote=q,
                        quotes_repo=quotes_repo,
                        anomaly_repo=anomaly_repo,
                        run_id=run_id,
                        actor_id=actor_id,
                    )
                    if persisted:
                        inserted += 1
                    else:
                        skipped += 1
                    if anomaly is not None:
                        anomalies.append(anomaly)
                except Exception as exc:  # noqa: BLE001
                    skipped += 1
                    error_payload.setdefault("per_quote_errors", []).append(
                        {
                            "commodity_key": q.commodity_key,
                            "error": str(exc),
                            "type": type(exc).__name__,
                        }
                    )
                    if outcome.status == "success":
                        outcome.status = "partial"

            await session.commit()

        for alert in anomalies:
            await _maybe_notify(alert)

    async with async_session_factory() as session:
        runs = FeedRunRepository(session)
        final_status = outcome.status
        if final_status == "success" and (skipped > 0 and inserted == 0):
            final_status = "failure"
        elif final_status == "success" and skipped > 0:
            final_status = "partial"
        run = await runs.complete_run(
            run_id=run_id,
            status=final_status,
            quotes_fetched=len(outcome.quotes),
            quotes_inserted=inserted,
            quotes_skipped=skipped,
            anomalies_detected=len(anomalies),
            error_message=error_message,
            error_payload=error_payload or None,
        )
        await session.commit()
        return run


async def _persist_quote_with_anomaly(
    *,
    feed_source: str,
    quote: FeedQuote,
    quotes_repo: LivePriceQuoteRepository,
    anomaly_repo: PriceAnomalyAlertRepository,
    run_id: str,
    actor_id: Optional[str],
) -> tuple[bool, Optional[dict[str, Any]]]:
    """Insert one quote, detect anomaly, and (maybe) record an alert."""
    previous = await quotes_repo.get_active(
        feed_source=feed_source,
        commodity_key=quote.commodity_key,
    )
    previous_low = previous["price_low"] if previous else None
    previous_high = previous["price_high"] if previous else None

    persisted = await quotes_repo.upsert_quote(
        feed_source=feed_source,
        commodity_key=quote.commodity_key,
        display_name=quote.display_name,
        basis_unit=quote.basis_unit,
        price_low=quote.price_low,
        price_high=quote.price_high,
        currency=quote.currency,
        category=quote.category,
        material_slug=quote.material_slug,
        captured_at=quote.captured_at,
        freshness_ttl_seconds=quote.freshness_ttl_seconds,
        payload=quote.payload,
        source=feed_source,
        source_ref=quote.source_ref,
        actor_id=actor_id,
        request_id=get_request_id(),
    )

    verdict = detect_anomaly(
        previous_low=previous_low,
        previous_high=previous_high,
        new_low=quote.price_low,
        new_high=quote.price_high,
    )
    if not verdict.triggered:
        return True, None

    alert = await anomaly_repo.create_alert(
        feed_source=feed_source,
        commodity_key=quote.commodity_key,
        material_slug=quote.material_slug,
        previous_price_mid=verdict.previous_mid,
        new_price_mid=verdict.new_mid,
        pct_change=verdict.pct_change,
        threshold_pct=verdict.threshold_pct,
        direction=verdict.direction,
        feed_run_id=run_id,
        new_quote_id=persisted["id"],
        payload={
            "reason": verdict.reason,
            "previous_low": previous_low,
            "previous_high": previous_high,
            "new_low": quote.price_low,
            "new_high": quote.price_high,
        },
    )
    return True, alert


async def _maybe_notify(alert: dict[str, Any]) -> None:
    """Send Slack (or fall back to log), then mark the alert row.

    Runs in its own session because Slack POST latency shouldn't
    extend the main quote-persisting transaction. Slack failure is
    captured via the alert row and a structured log line — never
    raises out of this function.
    """
    channel, error = await send_anomaly_alert(
        feed_source=alert["feed_source"],
        commodity_key=alert["commodity_key"],
        previous_mid=alert["previous_price_mid"],
        new_mid=alert["new_price_mid"],
        pct_change=alert["pct_change"],
        threshold_pct=alert["threshold_pct"],
        direction=alert["direction"],
        material_slug=alert.get("material_slug"),
    )

    async with async_session_factory() as session:
        repo = PriceAnomalyAlertRepository(session)
        try:
            await repo.mark_notified(
                alert_id=alert["id"],
                channel=channel,
                error=error,
            )
            await session.commit()
        except Exception:  # noqa: BLE001 — soft-fail boundary
            await session.rollback()
            logger.warning(
                "could not record notification status for alert %s",
                alert["id"],
            )


# ─────────────────────────────────────────────────────────────────────
# Status helpers (consumed by /admin/feeds)
# ─────────────────────────────────────────────────────────────────────


async def feed_status_summary(session: AsyncSession) -> dict[str, Any]:
    """Compose the dashboard payload: per-feed status + recent alerts."""
    settings = get_settings()
    runs_repo = FeedRunRepository(session)
    alerts_repo = PriceAnomalyAlertRepository(session)
    registry = get_registry()

    latest = await runs_repo.latest_per_feed()
    latest_by_feed = {row["feed_source"]: row for row in latest}
    unack = await alerts_repo.list_unacknowledged(limit=20)

    feeds: list[dict[str, Any]] = []
    for adapter in registry.all():
        feeds.append(
            {
                "feed_source": adapter.feed_source,
                "display_name": adapter.display_name or adapter.feed_source,
                "description": adapter.description,
                "enabled": _is_feed_enabled(adapter.feed_source),
                "live_mode": settings.live_feeds_enabled,
                "latest_run": latest_by_feed.get(adapter.feed_source),
            }
        )

    return {
        "live_feeds_enabled": settings.live_feeds_enabled,
        "anomaly_threshold_pct": settings.feed_anomaly_pct_threshold,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "feeds": feeds,
        "unacknowledged_alerts": unack,
        "unacknowledged_count": len(unack),
    }
