"""DB-backed standards accessors with check helpers.

Public surface
--------------
- :func:`get_standard`              — single row by (slug, category, jurisdiction).
- :func:`resolve_standard`          — jurisdiction-aware (specific → baseline).
- :func:`list_standards_by_category` — list all of a category for a jurisdiction.
- :func:`check_door_width`          — async equivalent of legacy ``check_door``.
- :func:`check_corridor_width`      — async equivalent of legacy ``check_corridor``.
- :func:`check_room_area`           — async equivalent of legacy ``area_check``.

The check helpers return the same status envelope shape the legacy
functions did (``{"status": ..., "message": ..., "reference": ...}``)
so future agent-tool wrappers can use them directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.standards import StandardsRepository


# ─────────────────────────────────────────────────────────────────────
# Reads
# ─────────────────────────────────────────────────────────────────────


async def get_standard(
    session: AsyncSession,
    *,
    slug: str,
    category: str,
    jurisdiction: str = "india_nbc",
    when: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Exact ``(slug, category, jurisdiction)`` lookup.

    Returns the full row dict or ``None``. Use :func:`resolve_standard`
    for jurisdiction-aware fallback to the baseline.
    """
    repo = StandardsRepository(session)
    return await repo.get_active(
        slug=slug, category=category, jurisdiction=jurisdiction, when=when
    )


async def resolve_standard(
    session: AsyncSession,
    *,
    slug: str,
    category: str,
    jurisdiction: str = "india_nbc",
    when: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Pick the most specific available standard.

    Falls back to ``india_nbc`` if the requested jurisdiction has no
    override. Use this in 99% of agent / cost-engine paths.
    """
    repo = StandardsRepository(session)
    return await repo.resolve(
        slug=slug, category=category, jurisdiction=jurisdiction, when=when
    )


async def list_standards_by_category(
    session: AsyncSession,
    *,
    category: str,
    subcategory: Optional[str] = None,
    jurisdiction: str = "india_nbc",
    when: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """All current rows in a category × jurisdiction."""
    repo = StandardsRepository(session)
    return await repo.list_active(
        category=category,
        subcategory=subcategory,
        jurisdiction=jurisdiction,
        when=when,
    )


# ─────────────────────────────────────────────────────────────────────
# Check helpers — async equivalents of legacy validators
# ─────────────────────────────────────────────────────────────────────


async def check_door_width(
    session: AsyncSession,
    *,
    door_type: str,
    width_mm: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Validate a door width against the BRD/NBC standard.

    Returns ``{status, message, reference, source_section}`` matching
    the legacy ``clearances.check_door`` shape, plus citation fields
    Stage 11 transparency uses.
    """
    row = await resolve_standard(
        session,
        slug=f"door_{door_type}",
        category="clearance",
        jurisdiction=jurisdiction,
    )
    if row is None:
        return {
            "status": "unknown",
            "message": f"No standard for door type {door_type!r}.",
            "reference": None,
            "source_section": None,
        }
    band = row["data"].get("width_mm") or [None, None]
    lo, hi = band
    base = {
        "reference": row.get("notes") or row["display_name"],
        "source_section": row.get("source_section"),
        "jurisdiction_used": row["jurisdiction"],
    }
    if lo is None or hi is None:
        return {**base, "status": "unknown", "message": "Door spec lacks width band."}
    if width_mm < lo:
        return {
            **base,
            "status": "warn_low",
            "message": f"{door_type} door width {width_mm}mm below {lo}mm.",
        }
    if width_mm > hi * 1.5:
        return {
            **base,
            "status": "warn_high",
            "message": f"{door_type} door width {width_mm}mm unusually large.",
        }
    return {**base, "status": "ok", "message": f"Within {lo}-{hi}mm."}


async def check_corridor_width(
    session: AsyncSession,
    *,
    segment: str,
    width_mm: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    row = await resolve_standard(
        session,
        slug=f"corridor_{segment}",
        category="clearance",
        jurisdiction=jurisdiction,
    )
    if row is None:
        return {
            "status": "unknown",
            "message": f"No standard for corridor {segment!r}.",
            "reference": None,
            "source_section": None,
        }
    min_w = row["data"].get("min_width_mm")
    base = {
        "reference": row.get("notes") or row["display_name"],
        "source_section": row.get("source_section"),
        "jurisdiction_used": row["jurisdiction"],
    }
    if min_w is None:
        return {**base, "status": "unknown", "message": "Corridor spec lacks min_width_mm."}
    if width_mm < float(min_w):
        return {
            **base,
            "status": "warn_low",
            "message": f"{segment} corridor {width_mm}mm below minimum {min_w}mm.",
        }
    return {**base, "status": "ok", "message": f"Meets >= {min_w}mm."}


async def check_stair_dimensions(
    session: AsyncSession,
    *,
    stair_type: str,
    rise_mm: float | None = None,
    tread_mm: float | None = None,
    width_mm: float | None = None,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Validate stair geometry against the BRD/NBC stair standard.

    ``stair_type`` ∈ ``residential`` | ``commercial`` | ``fire_escape``.
    Any of ``rise_mm`` / ``tread_mm`` / ``width_mm`` may be omitted —
    the function only checks what was provided. Returns the standard
    citation shape (``status``, ``message``, ``reference``,
    ``source_section``, ``jurisdiction_used``).

    BRD §1B example: residential 180 mm rise / 280 mm tread. The DB
    seed allows 150-200 mm rise and 250-300 mm tread for residential,
    so 180 / 280 sits well inside the band.
    """
    row = await resolve_standard(
        session,
        slug=f"stair_{stair_type}",
        category="clearance",
        jurisdiction=jurisdiction,
    )
    if row is None:
        return {
            "status": "unknown",
            "message": f"No standard for stair type {stair_type!r}.",
            "reference": None,
            "source_section": None,
        }
    data = row.get("data") or {}
    base = {
        "reference": row.get("notes") or row["display_name"],
        "source_section": row.get("source_section"),
        "jurisdiction_used": row["jurisdiction"],
    }

    rise_band = data.get("rise_mm")
    tread_band = data.get("tread_mm")
    min_width = data.get("min_width_mm")

    issues: list[str] = []
    if rise_mm is not None and isinstance(rise_band, list) and len(rise_band) == 2:
        lo, hi = float(rise_band[0]), float(rise_band[1])
        if rise_mm < lo:
            issues.append(
                f"{stair_type} stair rise {rise_mm}mm below minimum {lo:.0f}mm"
            )
        elif rise_mm > hi:
            issues.append(
                f"{stair_type} stair rise {rise_mm}mm above maximum {hi:.0f}mm"
            )
    if tread_mm is not None and isinstance(tread_band, list) and len(tread_band) == 2:
        lo, hi = float(tread_band[0]), float(tread_band[1])
        if tread_mm < lo:
            issues.append(
                f"{stair_type} stair tread {tread_mm}mm below minimum {lo:.0f}mm"
            )
        elif tread_mm > hi:
            issues.append(
                f"{stair_type} stair tread {tread_mm}mm above maximum {hi:.0f}mm"
            )
    if width_mm is not None and min_width is not None:
        if width_mm < float(min_width):
            issues.append(
                f"{stair_type} stair width {width_mm}mm below minimum {min_width}mm"
            )

    if not issues:
        return {**base, "status": "ok", "message": "Within stair standard."}
    return {
        **base,
        "status": "warn_low",
        "message": " · ".join(issues),
    }


async def check_room_area(
    session: AsyncSession,
    *,
    room_type: str,
    area_m2: float,
    segment: str = "residential",
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Validate a room area against the BRD/NBC space standard.

    ``segment`` is the high-level category — ``residential`` |
    ``commercial`` | ``hospitality``. We map it to the seeded
    ``subcategory`` (``residential_room``, ``commercial_room``,
    ``hospitality_room``) for traceability.
    """
    row = await resolve_standard(
        session,
        slug=room_type,
        category="space",
        jurisdiction=jurisdiction,
    )
    if row is None:
        return {
            "status": "unknown_room",
            "message": f"No standard for {segment}/{room_type}.",
            "reference": None,
            "source_section": None,
        }
    data = row["data"]
    base = {
        "reference": row.get("notes") or row["display_name"],
        "source_section": row.get("source_section"),
        "jurisdiction_used": row["jurisdiction"],
    }
    min_area = data.get("min_area_m2")
    max_area = data.get("max_typical_m2")
    if min_area is not None and area_m2 < float(min_area):
        return {
            **base,
            "status": "warn_low",
            "message": f"{room_type} area {area_m2:.1f} m^2 below minimum {min_area} m^2.",
        }
    if max_area is not None and area_m2 > float(max_area) * 1.5:
        return {
            **base,
            "status": "warn_high",
            "message": (
                f"{room_type} area {area_m2:.1f} m^2 significantly exceeds "
                f"typical {max_area} m^2."
            ),
        }
    return {**base, "status": "ok", "message": "Within standard range."}
