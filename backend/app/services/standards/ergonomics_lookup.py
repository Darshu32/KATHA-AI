"""Async DB-backed ergonomics lookups (Stage 3E).

Mirrors :func:`app.knowledge.ergonomics.check_range` and adds direct
fetchers for chair / table / bed / storage envelopes.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.standards import StandardsRepository


async def get_ergonomics(
    session: AsyncSession,
    *,
    item_group: str,
    item: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the full envelope for ``(group, item)``.

    Example::

        spec = await get_ergonomics(session, item_group="chair", item="dining_chair")
        # spec["seat_height_mm"] → [400, 450]
    """
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"ergonomics_{item_group}_{item}",
        category="space",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def list_ergonomics_for_group(
    session: AsyncSession,
    *,
    item_group: str,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    """All ergonomics rows for chairs / tables / beds / storage."""
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="space",
        subcategory="furniture_ergonomics",
        jurisdiction=jurisdiction,
    )
    return [r for r in rows if r["data"].get("item_group") == item_group]


async def check_range(
    session: AsyncSession,
    *,
    category: str,
    item: str,
    dim: str,
    value_mm: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Validate one dimension against the ergonomic range.

    Drop-in async equivalent of :func:`app.knowledge.ergonomics.check_range`.
    Returns ``{"status", "message"}`` with ``status`` in
    ``ok``/``warn_low``/``warn_high``/``unknown``.
    """
    spec = await get_ergonomics(
        session, item_group=category.lower(), item=item, jurisdiction=jurisdiction
    )
    if spec is None:
        return {"status": "unknown", "message": f"No range for {category}/{item}."}
    key = dim if dim in spec else f"{dim}_mm"
    if key not in spec:
        return {"status": "unknown", "message": f"No dim '{dim}' for {item}."}
    band = spec[key]
    if not isinstance(band, list) or len(band) != 2:
        return {
            "status": "unknown",
            "message": f"{item}.{dim} is not a band (got {band!r}).",
        }
    lo, hi = float(band[0]), float(band[1])
    if value_mm < lo:
        return {
            "status": "warn_low",
            "message": f"{item}.{dim}={value_mm}mm below min {lo}mm.",
        }
    if value_mm > hi:
        return {
            "status": "warn_high",
            "message": f"{item}.{dim}={value_mm}mm above max {hi}mm.",
        }
    return {"status": "ok", "message": f"Within {lo}-{hi}mm."}


async def bed_under_storage_band(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[tuple[int, int]]:
    """Convenience for the ``BED_UNDER_STORAGE_MM`` legacy constant."""
    spec = await get_ergonomics(
        session,
        item_group="bed",
        item="under_storage",
        jurisdiction=jurisdiction,
    )
    if spec is None:
        return None
    band = spec.get("under_storage_height_mm")
    if not isinstance(band, list) or len(band) != 2:
        return None
    return int(band[0]), int(band[1])
