"""Repository for ``price_anomaly_alerts``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.database import _uuid
from app.models.feeds import PriceAnomalyAlert
from app.repositories.live_pricing._serialize import anomaly_to_dict


class PriceAnomalyAlertRepository:
    def __init__(self, session) -> None:
        self.session = session

    async def create_alert(
        self,
        *,
        feed_source: str,
        commodity_key: str,
        previous_price_mid: float,
        new_price_mid: float,
        pct_change: float,
        threshold_pct: float,
        direction: str,
        material_slug: Optional[str] = None,
        feed_run_id: Optional[str] = None,
        new_quote_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if direction not in {"up", "down"}:
            raise ValueError(f"Invalid direction: {direction!r}")
        row = PriceAnomalyAlert(
            id=_uuid(),
            feed_source=feed_source,
            commodity_key=commodity_key,
            material_slug=material_slug,
            previous_price_mid=previous_price_mid,
            new_price_mid=new_price_mid,
            pct_change=pct_change,
            threshold_pct=threshold_pct,
            direction=direction,
            feed_run_id=feed_run_id,
            new_quote_id=new_quote_id,
            payload=payload or {},
        )
        self.session.add(row)
        await self.session.flush()
        return anomaly_to_dict(row)

    async def mark_notified(
        self,
        *,
        alert_id: str,
        channel: str,
        error: Optional[str] = None,
    ) -> dict[str, Any]:
        row = await self.session.get(PriceAnomalyAlert, alert_id)
        if row is None:
            raise LookupError(f"PriceAnomalyAlert {alert_id!r} not found")
        row.notified_channel = channel
        if error:
            row.notification_error = error
        else:
            row.notified_at = datetime.now(timezone.utc)
        await self.session.flush()
        return anomaly_to_dict(row)

    async def acknowledge(
        self,
        *,
        alert_id: str,
        actor_id: str,
    ) -> dict[str, Any]:
        row = await self.session.get(PriceAnomalyAlert, alert_id)
        if row is None:
            raise LookupError(f"PriceAnomalyAlert {alert_id!r} not found")
        row.acknowledged_at = datetime.now(timezone.utc)
        row.acknowledged_by = actor_id
        await self.session.flush()
        return anomaly_to_dict(row)

    async def list_unacknowledged(
        self,
        *,
        feed_source: Optional[str] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(PriceAnomalyAlert)
            .where(PriceAnomalyAlert.acknowledged_at.is_(None))
            .order_by(PriceAnomalyAlert.created_at.desc())
            .limit(limit)
        )
        if feed_source:
            stmt = stmt.where(PriceAnomalyAlert.feed_source == feed_source)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [anomaly_to_dict(r) for r in rows]

    async def list_recent(
        self,
        *,
        feed_source: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(PriceAnomalyAlert)
            .order_by(PriceAnomalyAlert.created_at.desc())
            .limit(limit)
        )
        if feed_source:
            stmt = stmt.where(PriceAnomalyAlert.feed_source == feed_source)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [anomaly_to_dict(r) for r in rows]
