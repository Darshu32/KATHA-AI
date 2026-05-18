"""Aggregator that pre-loads everything the Recommendations Engine LLM
stage cites — BRD §6.

Bundles the wood + metal catalogues, manufacturing lead-times + MOQ,
manufacturer margin by volume, and city price index into one dict the
``recommendations_service`` builder can slice from.

Caller passes the result into ``build_recommendations_knowledge(...,
recommendations_kb=pack)``. Builder falls back per-key to the legacy
literal when a sub-dict is missing.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.pricing import CityPriceIndexRepository
from app.services.pricing.knowledge_service import (
    load_cost_factor_bands,
    load_namespaced_factor_bands,
)
from app.services.standards.manufacturing_lookup import (
    bending_rule as _bending_rule_db,
    joinery_catalogue as _joinery_catalogue_db,
    lead_times_weeks_map,
    moq_units_map,
    tolerances_mm_map,
)
from app.services.standards.materials_lookup import (
    get_metal_brd_band,
    get_wood_brd_band,
    list_finishes,
    list_metals,
    list_woods,
)


def _strip_prefix(slug: str, prefix: str) -> str:
    return slug[len(prefix):] if slug.startswith(prefix) else slug


async def _wood_catalogue(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, Any]]:
    rows = await list_woods(session, jurisdiction=jurisdiction)
    return {
        _strip_prefix(r["slug"], "material_wood_"): dict(r.get("data") or {})
        for r in rows
        if r.get("slug") and r["slug"] != "material_wood_brd_band"
    }


async def _metal_catalogue(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, Any]]:
    rows = await list_metals(session, jurisdiction=jurisdiction)
    return {
        _strip_prefix(r["slug"], "material_metal_"): dict(r.get("data") or {})
        for r in rows
        if r.get("slug") and r["slug"] != "material_metal_brd_band"
    }


async def load_recommendations_pack(
    session: AsyncSession,
    *,
    city: Optional[str] = None,
    jurisdiction: str = "india_nbc",
    when: Optional[datetime] = None,
) -> dict[str, Any]:
    """Return the recommendations-KB dict the builder needs.

    Shape (matches the legacy literal reads 1-for-1):

        {
          "wood_catalogue":   {species: data},
          "metal_catalogue":  {alloy: data},
          "lead_times_weeks": {discipline: [low, high]},
          "moq_units":        {kind: int},
          "manufacturer_margin_pct_by_volume": {tier: [low, high]},
          "city_price_index": float,
        }
    """
    wood_cat = await _wood_catalogue(session, jurisdiction=jurisdiction)
    metal_cat = await _metal_catalogue(session, jurisdiction=jurisdiction)
    lead_times = await lead_times_weeks_map(session, jurisdiction=jurisdiction)
    moq = await moq_units_map(session, jurisdiction=jurisdiction)
    mfg_margin = await load_namespaced_factor_bands(
        session, "manufacturer_margin_pct", when=when
    )

    city_index: float = 1.0
    if city:
        repo = CityPriceIndexRepository(session)
        row = await repo.resolve(city, when=when)
        if row:
            try:
                city_index = float(row["index_multiplier"])
            except (TypeError, ValueError, KeyError):
                city_index = 1.0

    return {
        "wood_catalogue": wood_cat,
        "metal_catalogue": metal_cat,
        "lead_times_weeks": lead_times,
        "moq_units": moq,
        "manufacturer_margin_pct_by_volume": mfg_margin,
        "city_price_index": city_index,
    }


async def _finishes_catalogue(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, Any]]:
    rows = await list_finishes(session, jurisdiction=jurisdiction)
    return {
        _strip_prefix(r["slug"], "material_finish_"): dict(r.get("data") or {})
        for r in rows
        if r.get("slug")
    }


async def load_knowledge_integration_pack(
    session: AsyncSession,
    *,
    city: Optional[str] = None,
    jurisdiction: str = "india_nbc",
    when: Optional[datetime] = None,
) -> dict[str, Any]:
    """Aggregator for the knowledge integration LLM slicer.

    Returns ``kb`` shape that
    :func:`knowledge_integration_service.build_knowledge_integration_slice`
    threads into each per-event-kind application helper. Keys match the
    legacy literal contract (``wood_catalogue``, ``metal_catalogue``,
    ``finishes_catalogue``, ``joinery_catalogue``, ``bending_rule``,
    ``tolerances_mm``, ``manufacturer_margin_pct_by_volume``,
    ``finish_cost_pct_of_material``, ``wood_finish_palette``,
    ``metal_finish_palette``, ``metal_fabrication_methods``).
    """
    wood_cat = await _wood_catalogue(session, jurisdiction=jurisdiction)
    metal_cat = await _metal_catalogue(session, jurisdiction=jurisdiction)
    finishes_cat = await _finishes_catalogue(session, jurisdiction=jurisdiction)
    joinery_cat = await _joinery_catalogue_db(session, jurisdiction=jurisdiction)
    bend_rule = await _bending_rule_db(session, jurisdiction=jurisdiction) or {}
    tolerances = await tolerances_mm_map(session, jurisdiction=jurisdiction)
    mfg_margin = await load_namespaced_factor_bands(
        session, "manufacturer_margin_pct", when=when
    )
    flat = await load_cost_factor_bands(
        session,
        ["finish_cost_pct_of_material", "waste_factor_pct"],
        when=when,
    )

    wood_band = await get_wood_brd_band(session, jurisdiction=jurisdiction) or {}
    metal_band = await get_metal_brd_band(session, jurisdiction=jurisdiction) or {}

    return {
        "wood_catalogue": wood_cat,
        "metal_catalogue": metal_cat,
        "finishes_catalogue": finishes_cat,
        "joinery_catalogue": joinery_cat,
        "bending_rule": dict(bend_rule),
        "tolerances_mm": tolerances,
        "manufacturer_margin_pct_by_volume": mfg_margin,
        "finish_cost_pct_of_material": flat.get("finish_cost_pct_of_material"),
        "waste_factor_pct": flat.get("waste_factor_pct"),
        "wood_finish_palette": list(wood_band.get("finish_palette") or []),
        "metal_finish_palette": list(metal_band.get("finish_palette") or []),
        "metal_fabrication_methods": list(
            metal_band.get("fabrication_methods") or []
        ),
    }
