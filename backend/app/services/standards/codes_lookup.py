"""Async DB-backed code lookups (Stage 3E).

Mirrors the legacy sync helpers in :mod:`app.knowledge.codes`,
:mod:`app.knowledge.ibc`, :mod:`app.knowledge.structural`, and
:mod:`app.knowledge.climate` while reading every value from the
versioned ``building_standards`` table.

The check helpers preserve legacy return shapes (``status`` /
``message`` / ``code`` / ``issue``) so the cost engine + spec services
+ future agent tools can swap to these with minimal disruption.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.standards import StandardsRepository


# ─────────────────────────────────────────────────────────────────────
# Generic accessors
# ─────────────────────────────────────────────────────────────────────


async def get_code(
    session: AsyncSession,
    *,
    slug: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Resolve one code row (with jurisdiction fallback to baseline)."""
    repo = StandardsRepository(session)
    return await repo.resolve(
        slug=slug, category="code", jurisdiction=jurisdiction
    )


async def get_code_data(
    session: AsyncSession,
    *,
    slug: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Convenience: resolve and return ``data`` only."""
    row = await get_code(session, slug=slug, jurisdiction=jurisdiction)
    return row["data"] if row else None


# ─────────────────────────────────────────────────────────────────────
# NBC India helpers
# ─────────────────────────────────────────────────────────────────────


async def nbc_minimum_room_dimensions(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session,
        slug="code_nbc_minimum_room_dimensions",
        jurisdiction=jurisdiction,
    )


async def check_room_against_nbc(
    session: AsyncSession,
    *,
    room_type: str,
    area_m2: float,
    short_side_m: float,
    height_m: float,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    """Drop-in async equivalent of :func:`app.knowledge.codes.check_room_against_nbc`."""
    nbc = await nbc_minimum_room_dimensions(
        session, jurisdiction=jurisdiction
    )
    if nbc is None:
        return [
            {
                "code": "NBC",
                "issue": "no minimum-room-dimensions row in DB",
            }
        ]

    issues: list[dict[str, Any]] = []
    if room_type in {"bedroom", "living_room", "dining_room", "study"}:
        if area_m2 < float(nbc["habitable_room_min_area_m2"]):
            issues.append(
                {
                    "code": "NBC Part 3",
                    "issue": (
                        f"Area {area_m2}m^2 < habitable min "
                        f"{nbc['habitable_room_min_area_m2']}"
                    ),
                }
            )
        if short_side_m < float(nbc["habitable_room_min_short_side_m"]):
            issues.append(
                {
                    "code": "NBC Part 3",
                    "issue": (
                        f"Short side {short_side_m}m < "
                        f"{nbc['habitable_room_min_short_side_m']}"
                    ),
                }
            )
        if height_m < float(nbc["habitable_room_min_height_m"]):
            issues.append(
                {
                    "code": "NBC Part 3",
                    "issue": (
                        f"Height {height_m}m < "
                        f"{nbc['habitable_room_min_height_m']}"
                    ),
                }
            )
    elif room_type == "kitchen":
        if area_m2 < float(nbc["kitchen_min_area_m2"]):
            issues.append(
                {
                    "code": "NBC Part 3",
                    "issue": (
                        f"Kitchen area {area_m2} < {nbc['kitchen_min_area_m2']}"
                    ),
                }
            )
    elif room_type == "bathroom":
        if area_m2 < float(nbc["bathroom_min_area_m2"]):
            issues.append(
                {
                    "code": "NBC Part 3",
                    "issue": (
                        f"Bathroom area {area_m2} < {nbc['bathroom_min_area_m2']}"
                    ),
                }
            )
    return issues


async def get_ecbc_targets(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session,
        slug="code_ecbc_envelope_targets",
        jurisdiction=jurisdiction,
    )


async def get_accessibility(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the accessibility profile for the given jurisdiction.

    For ``india_nbc``: Harmonised Guidelines + NBC Part 3.
    For ``international_ibc``: IBC Chapter 11 cross-refs ANSI A117.1 / ADA.
    """
    if jurisdiction == "international_ibc":
        return await get_code_data(
            session, slug="code_ibc_accessibility", jurisdiction=jurisdiction
        )
    return await get_code_data(
        session,
        slug="code_accessibility_india_general",
        jurisdiction=jurisdiction,
    )


async def get_fire_safety(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session,
        slug="code_fire_safety_india_general",
        jurisdiction=jurisdiction,
    )


# ─────────────────────────────────────────────────────────────────────
# IBC helpers
# ─────────────────────────────────────────────────────────────────────


async def list_ibc_occupancy_groups(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    repo = StandardsRepository(session)
    return await repo.list_active(
        category="code",
        subcategory="ibc_occupancy",
        jurisdiction="international_ibc",
    )


async def get_ibc_occupancy(
    session: AsyncSession,
    group: str,
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session,
        slug=f"code_ibc_occupancy_{group}",
        jurisdiction="international_ibc",
    )


async def get_ibc_egress(session: AsyncSession) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session, slug="code_ibc_egress", jurisdiction="international_ibc"
    )


async def get_iecc_envelope(
    session: AsyncSession,
    climate_zone: str,
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session,
        slug=f"code_iecc_envelope_{climate_zone}",
        jurisdiction="international_ibc",
    )


# ─────────────────────────────────────────────────────────────────────
# Structural helpers
# ─────────────────────────────────────────────────────────────────────


async def get_live_loads_is875(
    session: AsyncSession,
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session, slug="code_structural_live_loads_is875"
    )


async def get_dead_loads(session: AsyncSession) -> Optional[dict[str, Any]]:
    return await get_code_data(session, slug="code_structural_dead_loads")


async def get_seismic_zones(
    session: AsyncSession,
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session, slug="code_structural_seismic_zones_is1893"
    )


async def get_span_limits(session: AsyncSession) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session, slug="code_structural_span_limits"
    )


async def check_span(
    session: AsyncSession,
    *,
    material: str,
    span_m: float,
) -> dict[str, Any]:
    """Drop-in async equivalent of :func:`app.knowledge.structural.check_span`."""
    data = await get_span_limits(session)
    if data is None or material not in data.get("span_m", {}):
        return {"status": "unknown", "message": f"No span data for {material}."}
    lo, hi = data["span_m"][material]
    if span_m > float(hi):
        return {
            "status": "warn_high",
            "message": (
                f"Span {span_m}m exceeds {material} max {hi}m. "
                "Consider alternative."
            ),
        }
    if span_m < float(lo):
        return {
            "status": "ok",
            "message": f"Well within {material} range.",
        }
    return {
        "status": "ok",
        "message": f"Within {material} typical range {lo}-{hi}m.",
    }


async def get_foundation_by_soil(
    session: AsyncSession,
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session, slug="code_structural_foundation_by_soil"
    )


async def get_material_strengths(
    session: AsyncSession,
) -> Optional[dict[str, Any]]:
    return await get_code_data(
        session, slug="code_structural_material_strengths"
    )


# ─────────────────────────────────────────────────────────────────────
# Climate helpers
# ─────────────────────────────────────────────────────────────────────


async def get_climate_zone(
    session: AsyncSession,
    zone: Optional[str],
) -> Optional[dict[str, Any]]:
    """Resolve a climate-zone row by canonical key (alias-tolerant)."""
    if not zone:
        return None
    key = str(zone).strip().lower().replace("-", "_").replace(" ", "_")
    return await get_code_data(session, slug=f"code_climate_{key}")


async def list_climate_zones(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    repo = StandardsRepository(session)
    return await repo.list_active(
        category="code",
        subcategory="climate",
        jurisdiction="india_nbc",
    )
