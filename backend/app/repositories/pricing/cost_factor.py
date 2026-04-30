"""Repository for ``cost_factors``."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.db import BaseRepository
from app.models.pricing import CostFactor
from app.repositories.pricing._serialize import cost_factor_to_dict


class CostFactorRepository(BaseRepository[CostFactor]):
    model = CostFactor

    async def list_active(
        self,
        *,
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).order_by(CostFactor.factor_key)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [cost_factor_to_dict(r) for r in rows]

    async def get_active(
        self,
        factor_key: str,
        *,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(CostFactor.factor_key == factor_key)
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return cost_factor_to_dict(row) if row else None

    async def get_band(
        self,
        factor_key: str,
        *,
        default: tuple[float, float] | None = None,
        when: Optional[datetime] = None,
    ) -> tuple[float, float]:
        """Convenience: return ``(low, high)`` or fall back to ``default``.

        Used by the cost-engine knowledge service so a missing factor
        in DB doesn't crash the whole flow during early-stage rollout.
        """
        row = await self.get_active(factor_key, when=when)
        if row is None:
            if default is None:
                raise LookupError(f"Cost factor not found and no default: {factor_key!r}")
            return default
        return float(row["value_low"]), float(row["value_high"])

    async def history_for(self, factor_key: str) -> list[dict[str, Any]]:
        stmt = (
            select(CostFactor)
            .where(CostFactor.factor_key == factor_key)
            .order_by(CostFactor.version.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [cost_factor_to_dict(r) for r in rows]

    async def update_band(
        self,
        *,
        factor_key: str,
        new_low: float,
        new_high: float,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if new_high < new_low:
            raise ValueError(
                f"Invalid band ({new_low}, {new_high}); must satisfy low <= high"
            )

        previous = (
            await self.session.execute(
                self._current_select().where(CostFactor.factor_key == factor_key)
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(f"No current CostFactor for factor_key={factor_key!r}")

        new_row = await self.create_versioned(
            previous,
            {"value_low": new_low, "value_high": new_high},
            actor_id=actor_id,
            reason=reason,
            request_id=request_id,
        )
        return cost_factor_to_dict(new_row)
