"""Repository for ``trade_hour_estimates``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db import BaseRepository
from app.models.pricing import TradeHourEstimate
from app.repositories.pricing._serialize import trade_hour_to_dict


class TradeHourRepository(BaseRepository[TradeHourEstimate]):
    model = TradeHourEstimate

    async def list_active(
        self,
        *,
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).order_by(
            TradeHourEstimate.trade, TradeHourEstimate.complexity
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [trade_hour_to_dict(r) for r in rows]

    async def get_active(
        self,
        *,
        trade: str,
        complexity: str,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(
            TradeHourEstimate.trade == trade,
            TradeHourEstimate.complexity == complexity,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return trade_hour_to_dict(row) if row else None

    async def update_band(
        self,
        *,
        trade: str,
        complexity: str,
        new_low: float,
        new_high: float,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if new_low < 0 or new_high < new_low:
            raise ValueError(
                f"Invalid hours band ({new_low}, {new_high}); must satisfy 0 <= low <= high"
            )

        previous = (
            await self.session.execute(
                self._current_select().where(
                    TradeHourEstimate.trade == trade,
                    TradeHourEstimate.complexity == complexity,
                )
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(
                f"No current TradeHourEstimate for trade={trade!r} complexity={complexity!r}"
            )

        new_row = await self.create_versioned(
            previous,
            {"hours_low": new_low, "hours_high": new_high},
            actor_id=actor_id,
            reason=reason,
            request_id=request_id,
        )
        return trade_hour_to_dict(new_row)
