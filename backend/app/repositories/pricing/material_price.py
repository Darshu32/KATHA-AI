"""Repository for ``material_prices``.

Returns dicts (not ORM instances) so values are cache-safe and
session-independent. Stage 6 (RAG citations) and Stage 11 (transparency)
both rely on these dicts containing ``version`` + ``source`` so any
downstream artefact can prove provenance.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.db import BaseRepository
from app.models.pricing import MaterialPrice
from app.repositories.pricing._serialize import material_price_to_dict


class MaterialPriceRepository(BaseRepository[MaterialPrice]):
    """Read + write API for material prices.

    Reads are not cached at this layer — Stage 1 keeps the repository
    simple and lets the higher-level *knowledge service* attach its
    own ``@async_cached`` decorator. Caching at the repo level made
    invalidation trickier across versioned writes; we'll revisit
    after Stage 4.
    """

    model = MaterialPrice

    # ── Reads ──────────────────────────────────────────────────────────

    async def list_active(
        self,
        *,
        category: Optional[str] = None,
        region: Optional[str] = None,
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when)
        if category:
            stmt = stmt.where(MaterialPrice.category == category)
        if region:
            stmt = stmt.where(MaterialPrice.region == region)
        stmt = stmt.order_by(MaterialPrice.category, MaterialPrice.slug)
        rows = (await self.session.execute(stmt)).scalars().all()
        return [material_price_to_dict(r) for r in rows]

    async def get_active_by_slug(
        self,
        slug: str,
        *,
        region: str = "global",
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(
            MaterialPrice.slug == slug,
            MaterialPrice.region == region,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return material_price_to_dict(row) if row else None

    async def history_for_slug(
        self,
        slug: str,
        *,
        region: str = "global",
    ) -> list[dict[str, Any]]:
        """Every version of ``(slug, region)``, newest-first.

        Soft-deleted rows are *included* — the audit story is still
        useful even after a row is removed from active use.
        """
        stmt = (
            select(MaterialPrice)
            .where(
                MaterialPrice.slug == slug,
                MaterialPrice.region == region,
            )
            .order_by(MaterialPrice.version.desc())
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [material_price_to_dict(r) for r in rows]

    # ── Writes ─────────────────────────────────────────────────────────

    async def update_price(
        self,
        *,
        slug: str,
        region: str,
        new_low: float,
        new_high: float,
        actor_id: str | None = None,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Append a new version with updated price band.

        Wraps :meth:`BaseRepository.create_versioned` and returns the
        serialized new row. Caller must commit the session.
        """
        if new_low < 0 or new_high < new_low:
            raise ValueError(
                f"Invalid price band ({new_low}, {new_high}); "
                "must satisfy 0 <= low <= high"
            )

        previous = (
            await self.session.execute(
                self._current_select().where(
                    MaterialPrice.slug == slug,
                    MaterialPrice.region == region,
                )
            )
        ).scalar_one_or_none()
        if previous is None:
            raise LookupError(
                f"No current MaterialPrice for slug={slug!r} region={region!r}"
            )

        new_row = await self.create_versioned(
            previous,
            {"price_inr_low": new_low, "price_inr_high": new_high},
            actor_id=actor_id,
            reason=reason,
            request_id=request_id,
        )
        return material_price_to_dict(new_row)
