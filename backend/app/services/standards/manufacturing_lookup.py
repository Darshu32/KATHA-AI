"""Async DB-backed manufacturing lookups (Stage 3D).

Mirrors the legacy sync helpers (``tolerance_for``, ``lead_time_for``)
and adds new accessors for joinery, welding, MOQ, QA gates, and
process specs. Same return shapes as legacy where applicable.

Stage 4 will wrap these as agent tools (``lookup_tolerance``,
``lookup_joinery``, ``lookup_lead_time``, ``list_qa_gates``).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.standards import StandardsRepository


async def _resolve_data(
    session: AsyncSession,
    *,
    slug: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=slug, category="manufacturing", jurisdiction=jurisdiction
    )
    return row["data"] if row else None


# ─────────────────────────────────────────────────────────────────────
# Tolerances
# ─────────────────────────────────────────────────────────────────────


async def tolerance_for(
    session: AsyncSession,
    category: str,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[float]:
    """Return the ±mm tolerance for a category, or ``None`` if unknown.

    Drop-in replacement for :func:`app.knowledge.manufacturing.tolerance_for`.
    """
    data = await _resolve_data(
        session, slug=f"mfg_tolerance_{category}", jurisdiction=jurisdiction
    )
    if data is None:
        return None
    return float(data["tolerance_plus_minus_mm"])


async def list_tolerances(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    repo = StandardsRepository(session)
    return await repo.list_active(
        category="manufacturing",
        subcategory="tolerance",
        jurisdiction=jurisdiction,
    )


# ─────────────────────────────────────────────────────────────────────
# Lead times + MOQ
# ─────────────────────────────────────────────────────────────────────


async def lead_time_for(
    session: AsyncSession,
    category: str,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[tuple[int, int]]:
    """Return ``(weeks_low, weeks_high)`` for a manufacturing category.

    Drop-in replacement for :func:`app.knowledge.manufacturing.lead_time_for`.
    """
    data = await _resolve_data(
        session, slug=f"mfg_lead_time_{category}", jurisdiction=jurisdiction
    )
    if data is None:
        return None
    return int(data["weeks_low"]), int(data["weeks_high"])


async def moq_for(
    session: AsyncSession,
    category: str,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[int]:
    data = await _resolve_data(
        session, slug=f"mfg_moq_{category}", jurisdiction=jurisdiction
    )
    if data is None:
        return None
    return int(data["min_order_qty"])


# ─────────────────────────────────────────────────────────────────────
# Joinery + welding
# ─────────────────────────────────────────────────────────────────────


async def joinery_lookup(
    session: AsyncSession,
    joinery_type: str,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the full joinery spec dict (strength, difficulty, use, tolerance_mm)."""
    return await _resolve_data(
        session,
        slug=f"mfg_joinery_{joinery_type}",
        jurisdiction=jurisdiction,
    )


async def list_joinery_types(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    repo = StandardsRepository(session)
    return await repo.list_active(
        category="manufacturing",
        subcategory="joinery",
        jurisdiction=jurisdiction,
    )


async def welding_lookup(
    session: AsyncSession,
    method: str,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    return await _resolve_data(
        session,
        slug=f"mfg_welding_{method}",
        jurisdiction=jurisdiction,
    )


# ─────────────────────────────────────────────────────────────────────
# QA gates
# ─────────────────────────────────────────────────────────────────────


async def list_qa_gates(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    """Return the 5 BRD canonical QA gates in the seeded order.

    BRD §1C order: material_inspection → dimension_verification →
    finish_inspection → assembly_check → safety_testing.
    """
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="manufacturing",
        subcategory="qa_gate",
        jurisdiction=jurisdiction,
    )
    # Sort by BRD canonical order (rows in DB sort alphabetically by
    # slug, which doesn't match BRD order — re-sort by canonical list).
    canonical_order = await _canonical_qa_order(session, jurisdiction=jurisdiction)
    if canonical_order:
        rank = {stage: i for i, stage in enumerate(canonical_order)}
        rows.sort(key=lambda r: rank.get(r["data"].get("stage"), 999))
    return rows


async def _canonical_qa_order(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> list[str]:
    data = await _resolve_data(
        session, slug="mfg_quality_gates_brd_spec", jurisdiction=jurisdiction
    )
    if not data:
        return []
    return list(data.get("stages") or [])


# ─────────────────────────────────────────────────────────────────────
# Process specs
# ─────────────────────────────────────────────────────────────────────


async def process_spec(
    session: AsyncSession,
    discipline: str,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the BRD §1C process spec for ``woodworking``,
    ``metal_fabrication``, ``upholstery_assembly``, or
    ``upholstery_detail``.
    """
    return await _resolve_data(
        session,
        slug=f"mfg_process_spec_{discipline}",
        jurisdiction=jurisdiction,
    )


async def precision_requirements(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the universal BRD §3A precision band dict."""
    return await _resolve_data(
        session,
        slug="mfg_precision_requirements",
        jurisdiction=jurisdiction,
    )


async def bending_rule(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    return await _resolve_data(
        session, slug="mfg_bending_rule", jurisdiction=jurisdiction
    )
