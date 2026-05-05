"""Row → dict serializers for the live-pricing repositories.

Same rationale as ``app.repositories.pricing._serialize``: detached
ORM instances are session-bound and cache-unfriendly; the cost-engine
knowledge dict consumes plain JSON-safe shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def live_quote_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "feed_source": row.feed_source,
        "commodity_key": row.commodity_key,
        "material_slug": row.material_slug,
        "display_name": row.display_name,
        "category": row.category,
        "basis_unit": row.basis_unit,
        "price_low": row.price_low,
        "price_high": row.price_high,
        "currency": row.currency,
        "captured_at": _iso(row.captured_at),
        "freshness_ttl_seconds": row.freshness_ttl_seconds,
        "payload": dict(row.payload or {}),
        "version": row.version,
        "is_current": row.is_current,
        "effective_from": _iso(row.effective_from),
        "effective_to": _iso(row.effective_to),
        "source": row.source,
        "source_ref": row.source_ref,
    }


def feed_run_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "feed_source": row.feed_source,
        "trigger": row.trigger,
        "started_at": _iso(row.started_at),
        "completed_at": _iso(row.completed_at),
        "duration_ms": row.duration_ms,
        "status": row.status,
        "quotes_fetched": row.quotes_fetched,
        "quotes_inserted": row.quotes_inserted,
        "quotes_skipped": row.quotes_skipped,
        "anomalies_detected": row.anomalies_detected,
        "error_message": row.error_message,
        "error_payload": dict(row.error_payload or {}),
        "request_id": row.request_id,
        "actor_id": row.actor_id,
        "created_at": _iso(row.created_at),
    }


def anomaly_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "feed_source": row.feed_source,
        "commodity_key": row.commodity_key,
        "material_slug": row.material_slug,
        "previous_price_mid": row.previous_price_mid,
        "new_price_mid": row.new_price_mid,
        "pct_change": row.pct_change,
        "threshold_pct": row.threshold_pct,
        "direction": row.direction,
        "feed_run_id": row.feed_run_id,
        "new_quote_id": row.new_quote_id,
        "notified_channel": row.notified_channel,
        "notified_at": _iso(row.notified_at),
        "notification_error": row.notification_error,
        "acknowledged_at": _iso(row.acknowledged_at),
        "acknowledged_by": row.acknowledged_by,
        "payload": dict(row.payload or {}),
        "created_at": _iso(row.created_at),
    }
