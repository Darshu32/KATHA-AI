"""Repository for ``live_price_quotes``.

Reads honour the standard "active = current + within effective dates"
filter from :class:`BaseRepository`. Writes append a new version per
``(feed_source, commodity_key)`` so the prior quote survives as the
historical version a Stage 1 pricing snapshot can replay against.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.db import BaseRepository
from app.models.feeds import LivePriceQuote
from app.repositories.live_pricing._serialize import live_quote_to_dict


class LivePriceQuoteRepository(BaseRepository[LivePriceQuote]):
    model = LivePriceQuote

    # ── Reads ──────────────────────────────────────────────────────────

    async def list_active(
        self,
        *,
        feed_source: Optional[str] = None,
        material_slug: Optional[str] = None,
        when: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when)
        if feed_source:
            stmt = stmt.where(LivePriceQuote.feed_source == feed_source)
        if material_slug:
            stmt = stmt.where(LivePriceQuote.material_slug == material_slug)
        stmt = stmt.order_by(
            LivePriceQuote.feed_source, LivePriceQuote.commodity_key
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [live_quote_to_dict(r) for r in rows]

    async def get_active(
        self,
        *,
        feed_source: str,
        commodity_key: str,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        when = when or datetime.now(timezone.utc)
        stmt = self._active_at(when).where(
            LivePriceQuote.feed_source == feed_source,
            LivePriceQuote.commodity_key == commodity_key,
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return live_quote_to_dict(row) if row else None

    async def get_active_for_material(
        self,
        material_slug: str,
        *,
        when: Optional[datetime] = None,
    ) -> Optional[dict[str, Any]]:
        """Most-recent live quote linked to a MaterialPrice slug.

        Returns the newest (by ``captured_at``) currently-active row.
        Used by the fallback chain to prefer live data over the seed.
        """
        when = when or datetime.now(timezone.utc)
        stmt = (
            self._active_at(when)
            .where(LivePriceQuote.material_slug == material_slug)
            .order_by(LivePriceQuote.captured_at.desc().nullslast())
            .limit(1)
        )
        row = (await self.session.execute(stmt)).scalar_one_or_none()
        return live_quote_to_dict(row) if row else None

    async def history(
        self,
        *,
        feed_source: str,
        commodity_key: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(LivePriceQuote)
            .where(
                LivePriceQuote.feed_source == feed_source,
                LivePriceQuote.commodity_key == commodity_key,
            )
            .order_by(LivePriceQuote.version.desc())
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return [live_quote_to_dict(r) for r in rows]

    # ── Writes ─────────────────────────────────────────────────────────

    async def upsert_quote(
        self,
        *,
        feed_source: str,
        commodity_key: str,
        display_name: str,
        basis_unit: str,
        price_low: float,
        price_high: float,
        currency: str = "INR",
        category: Optional[str] = None,
        material_slug: Optional[str] = None,
        captured_at: Optional[datetime] = None,
        freshness_ttl_seconds: int = 24 * 3600,
        payload: Optional[dict[str, Any]] = None,
        source: str = "feed",
        source_ref: Optional[str] = None,
        actor_id: Optional[str] = None,
        request_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Insert a brand-new logical row OR append a new version.

        The ``(feed_source, commodity_key)`` pair is the logical key.
        Existing current rows are demoted via :meth:`create_versioned`;
        absent ones get a fresh ``version=1`` row.
        """
        if price_low < 0 or price_high < price_low:
            raise ValueError(
                f"Invalid price band ({price_low}, {price_high}); "
                "must satisfy 0 <= low <= high"
            )

        previous = (
            await self.session.execute(
                self._current_select().where(
                    LivePriceQuote.feed_source == feed_source,
                    LivePriceQuote.commodity_key == commodity_key,
                )
            )
        ).scalar_one_or_none()

        common = {
            "display_name": display_name,
            "category": category,
            "basis_unit": basis_unit,
            "price_low": price_low,
            "price_high": price_high,
            "currency": currency,
            "material_slug": material_slug,
            "captured_at": captured_at or datetime.now(timezone.utc),
            "freshness_ttl_seconds": freshness_ttl_seconds,
            "payload": payload or {},
            "source": source,
            "source_ref": source_ref,
        }

        if previous is None:
            new_row = await self.create(
                {
                    "feed_source": feed_source,
                    "commodity_key": commodity_key,
                    **common,
                },
                actor_id=actor_id,
                reason=reason,
                request_id=request_id,
            )
        else:
            new_row = await self.create_versioned(
                previous,
                common,
                actor_id=actor_id,
                reason=reason or f"Refresh from {source}",
                request_id=request_id,
            )

        return live_quote_to_dict(new_row)
