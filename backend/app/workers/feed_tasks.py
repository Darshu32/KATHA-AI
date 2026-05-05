"""Celery tasks for Stage 12 live data feeds.

One task per feed source. The beat schedule (configured in
``celery_app.py``) fires each on its own cadence:

- MCX commodities         : every 6 hours
- FX rates                : every 6 hours
- GST classifications     : weekly (rates change rarely)
- Vendor catalogs         : daily

Each task is a thin wrapper around :func:`app.feeds.service.run_feed`
so the orchestration logic stays testable without Celery in the loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.feeds.service import run_feed
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _run_feed_sync(feed_source: str, *, trigger: str = "beat") -> dict[str, Any]:
    """Sync wrapper used by every Celery task. Logs + swallows."""
    try:
        return _run_async(run_feed(feed_source, trigger=trigger))
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.exception("feed task crashed: %s", feed_source)
        return {
            "feed_source": feed_source,
            "status": "failure",
            "error_message": f"task crashed: {exc}",
        }


@celery_app.task(bind=True, name="app.workers.feed_tasks.refresh_mcx_task")
def refresh_mcx_task(self, trigger: str = "beat") -> dict[str, Any]:
    logger.info("Task %s: refreshing MCX feed", self.request.id)
    return _run_feed_sync("mcx", trigger=trigger)


@celery_app.task(bind=True, name="app.workers.feed_tasks.refresh_fx_task")
def refresh_fx_task(self, trigger: str = "beat") -> dict[str, Any]:
    logger.info("Task %s: refreshing FX feed", self.request.id)
    return _run_feed_sync("fx_rbi", trigger=trigger)


@celery_app.task(bind=True, name="app.workers.feed_tasks.refresh_gst_task")
def refresh_gst_task(self, trigger: str = "beat") -> dict[str, Any]:
    logger.info("Task %s: refreshing GST feed", self.request.id)
    return _run_feed_sync("gst_cbic", trigger=trigger)


@celery_app.task(bind=True, name="app.workers.feed_tasks.refresh_vendor_jaquar_task")
def refresh_vendor_jaquar_task(self, trigger: str = "beat") -> dict[str, Any]:
    logger.info("Task %s: refreshing Jaquar feed", self.request.id)
    return _run_feed_sync("vendor:jaquar", trigger=trigger)


@celery_app.task(bind=True, name="app.workers.feed_tasks.refresh_vendor_kohler_task")
def refresh_vendor_kohler_task(self, trigger: str = "beat") -> dict[str, Any]:
    logger.info("Task %s: refreshing Kohler feed", self.request.id)
    return _run_feed_sync("vendor:kohler", trigger=trigger)


@celery_app.task(
    bind=True,
    name="app.workers.feed_tasks.refresh_vendor_asian_paints_task",
)
def refresh_vendor_asian_paints_task(
    self, trigger: str = "beat"
) -> dict[str, Any]:
    logger.info("Task %s: refreshing Asian Paints feed", self.request.id)
    return _run_feed_sync("vendor:asian_paints", trigger=trigger)
