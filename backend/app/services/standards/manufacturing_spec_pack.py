"""Aggregator that pre-loads everything the Manufacturing Spec Sheet
LLM stage cites — BRD §3C.

Produces a single ``manufacturing_kb`` dict shaped exactly like what
:func:`manufacturing_spec_service.build_manufacturing_spec_knowledge`
previously read from :mod:`app.knowledge.manufacturing` /
``materials`` / ``regional_materials`` literals, but every value now
sources from versioned ``building_standards`` + ``city_price_index``
rows.

Caller passes the result into ``build_manufacturing_spec_knowledge(
..., manufacturing_kb=pack)``. Per-key fallback to the legacy literal
keeps fresh dev DBs and uncalled paths working.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.pricing import CityPriceIndexRepository
from app.services.standards.manufacturing_lookup import (
    bending_rule,
    joinery_catalogue,
    lead_times_weeks_map,
    list_qa_gates,
    moq_units_map,
    precision_requirements,
    process_spec,
    quality_gates_stages,
    tolerances_mm_map,
    welding_catalogue,
)
from app.services.standards.materials_lookup import (
    get_finish,
    get_wood_brd_band,
    list_finishes,
)


def _strip_prefix(slug: str, prefix: str) -> str:
    return slug[len(prefix):] if slug.startswith(prefix) else slug


async def _finishes_catalogue(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, Any]]:
    rows = await list_finishes(session, jurisdiction=jurisdiction)
    return {
        _strip_prefix(r["slug"], "material_finish_"): dict(r.get("data") or {})
        for r in rows
        if r.get("slug")
    }


async def load_manufacturing_spec_pack(
    session: AsyncSession,
    *,
    city: Optional[str] = None,
    jurisdiction: str = "india_nbc",
    when: Optional[datetime] = None,
) -> dict[str, Any]:
    """Return the full manufacturing-KB dict the spec-sheet builder needs.

    Shape (matches the legacy literal reads 1-for-1)::

        {
          "manufacturing_brd": {
              "precision_requirements_mm": {...},
              "woodworking_brd_spec":      {...},
              "metal_fabrication_brd_spec":{...},
              "upholstery_assembly_brd_spec":{...},
              "tolerances_mm":             {category: mm},
              "lead_times_weeks":          {discipline: [low, high]},
              "moq_units":                 {kind: int},
          },
          "joinery_catalogue":  {method: data},
          "welding_catalogue":  {method: data},
          "bending_rule":       {...},
          "powder_coat_spec":   {...},
          "finishes_catalogue": {finish: data},
          "wood_finish_palette": [...],
          "qa_gates_catalogue":  [...],   # 5 BRD QA gates
          "qa_gate_keys_in_scope": [...], # canonical order
          "city_price_index":   float,
        }
    """
    precision = await precision_requirements(session, jurisdiction=jurisdiction) or {}
    woodworking = (
        await process_spec(session, "woodworking", jurisdiction=jurisdiction) or {}
    )
    metal_fab = (
        await process_spec(session, "metal_fabrication", jurisdiction=jurisdiction)
        or {}
    )
    upholstery_assembly = (
        await process_spec(session, "upholstery_assembly", jurisdiction=jurisdiction)
        or await process_spec(
            session, "upholstery_detail", jurisdiction=jurisdiction
        )
        or {}
    )
    tolerances = await tolerances_mm_map(session, jurisdiction=jurisdiction)
    lead_times = await lead_times_weeks_map(session, jurisdiction=jurisdiction)
    moq = await moq_units_map(session, jurisdiction=jurisdiction)
    joinery_cat = await joinery_catalogue(session, jurisdiction=jurisdiction)
    welding_cat = await welding_catalogue(session, jurisdiction=jurisdiction)
    bend_rule = await bending_rule(session, jurisdiction=jurisdiction) or {}

    powder_coat = (
        await get_finish(session, finish="powder_coat", jurisdiction=jurisdiction)
        or {}
    )
    finishes_cat = await _finishes_catalogue(
        session, jurisdiction=jurisdiction
    )

    wood_band = await get_wood_brd_band(session, jurisdiction=jurisdiction) or {}
    wood_finish_palette = list(wood_band.get("finish_palette") or [])

    qa_rows = await list_qa_gates(session, jurisdiction=jurisdiction)
    qa_stages = await quality_gates_stages(session, jurisdiction=jurisdiction)

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
        "manufacturing_brd": {
            "precision_requirements_mm": dict(precision),
            "woodworking_brd_spec": dict(woodworking),
            "metal_fabrication_brd_spec": dict(metal_fab),
            "upholstery_assembly_brd_spec": dict(upholstery_assembly),
            "tolerances_mm": dict(tolerances),
            "lead_times_weeks": dict(lead_times),
            "moq_units": dict(moq),
        },
        "joinery_catalogue": joinery_cat,
        "welding_catalogue": welding_cat,
        "bending_rule": dict(bend_rule),
        "powder_coat_spec": dict(powder_coat),
        "finishes_catalogue": finishes_cat,
        "wood_finish_palette": wood_finish_palette,
        "qa_gates_catalogue": [dict(g.get("data") or {}) for g in qa_rows],
        "qa_gate_keys_in_scope": list(qa_stages),
        "city_price_index": city_index,
    }
