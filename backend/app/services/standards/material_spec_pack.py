"""Aggregator that pre-loads everything the Material Specification Sheet
LLM stage cites — BRD §3B.

Produces a single ``materials_kb`` dict shaped exactly like what
:func:`material_spec_service.build_material_spec_knowledge` previously
read from :mod:`app.knowledge.materials` / ``manufacturing`` /
``regional_materials`` literals, but every value now sources from
versioned ``building_standards`` + ``city_price_index`` rows.

Caller passes the result into ``build_material_spec_knowledge(...,
materials_kb=pack)``. The builder falls back to the legacy literal per
key when a sub-dict is missing, so a fresh dev DB still produces a
usable sheet.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.pricing import CityPriceIndexRepository
from app.services.standards.manufacturing_lookup import process_spec
from app.services.standards.materials_lookup import (
    get_metal_brd_band,
    get_upholstery_brd_band,
    get_wood_brd_band,
    list_finishes,
    list_metals,
    list_upholstery_items,
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


async def _upholstery_catalogue(
    session: AsyncSession, *, jurisdiction: str
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Split rows into (upholstery, foam) catalogues matching the legacy
    ``materials.UPHOLSTERY`` and ``materials.FOAM`` literals.

    Leather + fabric rows go into the upholstery catalogue; foam rows
    into the foam catalogue.
    """
    # Legacy ``materials.UPHOLSTERY`` keyed entries as
    # ``leather_genuine_grade_A`` / ``fabric_cotton`` etc — we keep that
    # contract by stripping only the ``material_upholstery_`` prefix so
    # the family marker (``leather_`` / ``fabric_``) remains.
    upholstery: dict[str, dict[str, Any]] = {}
    foam: dict[str, dict[str, Any]] = {}
    for sub in ("leather", "fabric"):
        rows = await list_upholstery_items(
            session, subcategory=sub, jurisdiction=jurisdiction
        )
        for r in rows:
            slug = r.get("slug") or ""
            key = _strip_prefix(slug, "material_upholstery_")
            upholstery[key] = dict(r.get("data") or {})
    # Legacy ``materials.FOAM`` keyed by bare grade (``HD36``, ``HR40``).
    foam_rows = await list_upholstery_items(
        session, subcategory="foam", jurisdiction=jurisdiction
    )
    for r in foam_rows:
        slug = r.get("slug") or ""
        key = _strip_prefix(slug, "material_foam_")
        foam[key] = dict(r.get("data") or {})
    return upholstery, foam


async def _finishes_catalogue(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, Any]]:
    rows = await list_finishes(session, jurisdiction=jurisdiction)
    return {
        _strip_prefix(r["slug"], "material_finish_"): dict(r.get("data") or {})
        for r in rows
        if r.get("slug")
    }


async def load_material_spec_pack(
    session: AsyncSession,
    *,
    city: Optional[str] = None,
    jurisdiction: str = "india_nbc",
    when: Optional[datetime] = None,
) -> dict[str, Any]:
    """Return the full materials-KB dict the spec-sheet builder needs.

    Shape (matches the legacy literal reads in
    ``build_material_spec_knowledge`` 1-for-1)::

        {
          "wood_catalogue":          {species: data},
          "wood_brd": {
              "ranges":             {density_kg_m3: [..], mor_mpa: [..], ...},
              "finish_palette":     [...],
          },
          "metal_catalogue":         {alloy: data},
          "metal_brd": {
              "specs":              {per_metal subdict},
              "cost_inr_kg":        [low, high],
              "finish_palette":     [...],
              "fabrication":        [...],
          },
          "upholstery_catalogue":    {item: data},
          "upholstery_brd": {
              "leather":            {...},
              "fabric":             {...},
              "durability":         {...},
              "colourfastness_min_of_5": int,
          },
          "foam_catalogue":          {grade: data},
          "foam_brd":                {...},
          "upholstery_assembly_brd": {...},
          "finishes_catalogue":      {finish: data},
          "city_price_index":        float,
        }
    """
    wood_cat = await _wood_catalogue(session, jurisdiction=jurisdiction)
    wood_band = await get_wood_brd_band(session, jurisdiction=jurisdiction) or {}
    wood_brd = {
        "ranges": {
            k: list(v) if isinstance(v, (list, tuple)) else v
            for k, v in wood_band.items()
            if k != "finish_palette" and k != "material_family"
        },
        "finish_palette": list(wood_band.get("finish_palette") or []),
    }

    metal_cat = await _metal_catalogue(session, jurisdiction=jurisdiction)
    metal_band = await get_metal_brd_band(session, jurisdiction=jurisdiction) or {}
    metal_brd = {
        "specs": dict(metal_band.get("per_metal") or {}),
        "cost_inr_kg": list(metal_band.get("cost_inr_kg") or []),
        "finish_palette": list(metal_band.get("finish_palette") or []),
        "fabrication": list(metal_band.get("fabrication_methods") or []),
    }

    upholstery_cat, foam_cat = await _upholstery_catalogue(
        session, jurisdiction=jurisdiction
    )
    upholstery_band = (
        await get_upholstery_brd_band(session, jurisdiction=jurisdiction) or {}
    )
    upholstery_brd = {
        "leather": dict(upholstery_band.get("leather") or {}),
        "fabric": dict(upholstery_band.get("fabric") or {}),
        "durability": dict(upholstery_band.get("durability_rubs") or {}),
        "colourfastness_min_of_5": upholstery_band.get("colourfastness_min"),
    }
    foam_brd = dict(upholstery_band.get("foam") or {})

    assembly_brd = (
        await process_spec(
            session, "upholstery_assembly", jurisdiction=jurisdiction
        )
        or await process_spec(
            session, "upholstery_detail", jurisdiction=jurisdiction
        )
        or {}
    )

    finishes_cat = await _finishes_catalogue(session, jurisdiction=jurisdiction)

    city_index: float = 1.0
    if city:
        city_repo = CityPriceIndexRepository(session)
        row = await city_repo.resolve(city, when=when)
        if row:
            try:
                city_index = float(row["index_multiplier"])
            except (TypeError, ValueError, KeyError):
                city_index = 1.0

    return {
        "wood_catalogue": wood_cat,
        "wood_brd": wood_brd,
        "metal_catalogue": metal_cat,
        "metal_brd": metal_brd,
        "upholstery_catalogue": upholstery_cat,
        "upholstery_brd": upholstery_brd,
        "foam_catalogue": foam_cat,
        "foam_brd": foam_brd,
        "upholstery_assembly_brd": dict(assembly_brd),
        "finishes_catalogue": finishes_cat,
        "city_price_index": city_index,
    }
