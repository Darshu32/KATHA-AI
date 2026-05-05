"""Fallback chain for material price lookups.

The cost engine should never crash because a feed is down. The
chain in :func:`resolve_price_for_material` walks a strict order of
fallbacks and tags the resolved value with the *tier* it landed on,
so the snapshot banner can render the right confidence label:

  1. ``live``        — live quote from a feed adapter, freshness is
                        ``LIVE`` or ``RECENT``.
  2. ``cached``      — live quote, freshness ``STALE`` (older than the
                        recent band but inside the stale band).
  3. ``seed``        — ``MaterialPrice`` row from the Stage-1 baseline.
  4. ``unavailable`` — nothing on file. Caller decides how to surface.

Every tier returns a :class:`ResolvedPrice` with a uniform shape so
downstream code (knowledge_service.py, transparency banner) never
has to switch on the tier to read the band.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.feeds.freshness import (
    FreshnessLevel,
    classify_freshness,
    freshness_envelope,
)
from app.repositories.live_pricing import LivePriceQuoteRepository
from app.repositories.pricing import MaterialPriceRepository


@dataclass
class ResolvedPrice:
    """Result of a fallback-chain lookup.

    ``tier`` ∈ ``{live, cached, seed, unavailable}`` — the layer that
    served the value. ``available`` is False only when ``tier ==
    'unavailable'``; in that case ``price_low``/``price_high`` are
    zero and the snapshot will render a "data unavailable" badge.
    """

    tier: str
    available: bool
    material_slug: str
    price_low: float
    price_high: float
    currency: str = "INR"
    basis_unit: str = ""
    freshness: dict[str, Any] = field(default_factory=dict)
    source: str = ""
    source_ref: Optional[str] = None
    quote_id: Optional[str] = None
    seed_id: Optional[str] = None
    seed_version: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tier": self.tier,
            "available": self.available,
            "material_slug": self.material_slug,
            "price_low": self.price_low,
            "price_high": self.price_high,
            "currency": self.currency,
            "basis_unit": self.basis_unit,
            "freshness": self.freshness,
            "source": self.source,
            "source_ref": self.source_ref,
            "quote_id": self.quote_id,
            "seed_id": self.seed_id,
            "seed_version": self.seed_version,
        }

    @property
    def is_live(self) -> bool:
        return self.tier in {"live", "cached"}


_UNAVAILABLE_FRESHNESS = {
    "level": FreshnessLevel.UNKNOWN.value,
    "age_seconds": None,
    "age_human": "unavailable",
    "captured_at": None,
}


async def resolve_price_for_material(
    session: AsyncSession,
    *,
    material_slug: str,
    region: str = "global",
    when: Optional[datetime] = None,
) -> ResolvedPrice:
    """Resolve the price for a material across the fallback chain.

    The chain stops at the first tier that yields a usable row:

    1. **Live quote** — looked up by ``material_slug`` against
       ``live_price_quotes``. Accepted if freshness is
       :attr:`FreshnessLevel.LIVE` or :attr:`FreshnessLevel.RECENT`
       (returns ``tier='live'``), or :attr:`FreshnessLevel.STALE`
       (returns ``tier='cached'``). Expired live rows are *not*
       used; we fall through to seed instead so an estimate doesn't
       silently quote a 30-day-old MCX print.
    2. **Seed** — ``MaterialPrice`` row from the Stage-1 baseline.
    3. **Unavailable** — nothing on file at any tier.

    The function never raises for "no data found" — callers branch
    on :attr:`ResolvedPrice.available` instead.
    """
    quote_repo = LivePriceQuoteRepository(session)
    quote = await quote_repo.get_active_for_material(
        material_slug, when=when
    )

    if quote is not None:
        captured_at_raw = quote["captured_at"]
        captured_at_dt = _parse_iso(captured_at_raw)
        level = classify_freshness(captured_at_dt)

        if level in {FreshnessLevel.LIVE, FreshnessLevel.RECENT}:
            tier = "live"
        elif level == FreshnessLevel.STALE:
            tier = "cached"
        else:
            tier = None  # expired or unknown — fall through to seed

        if tier is not None:
            return ResolvedPrice(
                tier=tier,
                available=True,
                material_slug=material_slug,
                price_low=quote["price_low"],
                price_high=quote["price_high"],
                currency=quote["currency"],
                basis_unit=quote["basis_unit"],
                freshness=freshness_envelope(captured_at_dt),
                source=quote["source"] or quote["feed_source"],
                source_ref=quote.get("source_ref"),
                quote_id=quote["id"],
            )

    seed_repo = MaterialPriceRepository(session)
    seed = await seed_repo.get_active_by_slug(
        material_slug, region=region, when=when
    )
    if seed is not None:
        return ResolvedPrice(
            tier="seed",
            available=True,
            material_slug=material_slug,
            price_low=seed["price_inr_low"],
            price_high=seed["price_inr_high"],
            currency="INR",
            basis_unit=seed["basis_unit"],
            freshness=_UNAVAILABLE_FRESHNESS,
            source=seed["source"],
            source_ref=seed.get("source_ref"),
            seed_id=seed["id"],
            seed_version=seed["version"],
        )

    return ResolvedPrice(
        tier="unavailable",
        available=False,
        material_slug=material_slug,
        price_low=0.0,
        price_high=0.0,
        currency="INR",
        basis_unit="",
        freshness=_UNAVAILABLE_FRESHNESS,
        source="unavailable",
    )


def _parse_iso(value: Any) -> Optional[datetime]:
    """Tolerant ISO-8601 parser. Accepts ``str`` or ``datetime``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
