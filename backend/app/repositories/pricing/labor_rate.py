"""Repository for ``labor_rates``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.db import BaseRepository
from app.models.pricing import LaborRate
from app.repositories.pricing._serialize import labor_rate_to_dict


class LaborRateRepository(BaseRepository[LaborRate]):
    model = LaborRate

    async def list_active(
        self,
        *,
        region: str = "india",
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(LaborRate.region == region)
        stmt = stmt.order_by(LaborRate.trade)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [labor_rate_to_dict(r) for r in rows]

    async def get_active(
        self,
        *,
        trade: str,
        region: str = "india",
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(
            LaborRate.trade == trade,
            LaborRate.region == region,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return labor_rate_to_dict(row) if row else None

    async def history_for(
        self,
        *,
        trade: str,
        region: str = "india",
    ) -> list[dict[str, Any]]:
        stmt = (
            select(LaborRate)
            .where(LaborRate.trade == trade, LaborRate.region == region)
            .order_by(LaborRate.version.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [labor_rate_to_dict(r) for r in rows]

    async def update_rate(
        self,
        *,
        trade: str,
        region: str,
        new_low: float,
        new_high: float,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if new_low < 0 or new_high < new_low:
            raise ValueError(
                f"Invalid rate band ({new_low}, {new_high}); must satisfy 0 <= low <= high"
            )

        previous = (
            await self.session.execute(
                self._current_select().where(
                    LaborRate.trade == trade, LaborRate.region == region
                )
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(
                f"No current LaborRate for trade={trade!r} region={region!r}"
            )

        new_row = await self.create_versioned(
            previous,
            {"rate_inr_per_hour_low": new_low, "rate_inr_per_hour_high": new_high},
            actor_id=actor_id,
            reason=reason,
            request_id=request_id,
        )
        return labor_rate_to_dict(new_row)
