"""Repository for ``city_price_indices``.

Resolves alias keys (``new_delhi`` → ``delhi``, ``bangalore`` →
``bengaluru``) so callers can pass whatever the architect typed.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import or_

from app.db import BaseRepository
from app.models.pricing import CityPriceIndex
from app.repositories.pricing._serialize import city_index_to_dict


def _normalize(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


class CityPriceIndexRepository(BaseRepository[CityPriceIndex]):
    model = CityPriceIndex

    async def list_active(
        self,
        *,
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).order_by(CityPriceIndex.city_slug)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [city_index_to_dict(r) for r in rows]

    async def resolve(
        self,
        city: Optional[str],
        *,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        """Find the active row for ``city`` honouring aliases.

        Returns ``None`` when ``city`` is empty or unknown — caller
        should fall back to ``index_multiplier = 1.0`` (Delhi baseline).
        """
        if not city:
            return None
        slug = _normalize(city)
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(
            or_(
                CityPriceIndex.city_slug == slug,
                CityPriceIndex.aliases.any(slug),
            )
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return city_index_to_dict(row) if row else None

    async def index_for(
        self,
        city: Optional[str],
        *,
        when: Optional[datetime] = None,
    ) -> float:
        """Convenience: return the active multiplier or 1.0 if unknown."""
        row = await self.resolve(city, when=when)
        return float(row["index_multiplier"]) if row else 1.0

    async def update_multiplier(
        self,
        *,
        city_slug: str,
        new_multiplier: float,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        if new_multiplier <= 0:
            raise ValueError("multiplier must be positive")

        previous = (
            await self.session.execute(
                self._current_select().where(CityPriceIndex.city_slug == city_slug)
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(f"No current CityPriceIndex for city_slug={city_slug!r}")

        new_row = await self.create_versioned(
            previous,
            {"index_multiplier": new_multiplier},
            actor_id=actor_id,
            reason=reason,
            request_id=request_id,
        )
        return city_index_to_dict(new_row)
