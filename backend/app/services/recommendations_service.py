"""LLM-driven Recommendations Engine (BRD Layer 6).

The advisor that fires across the design pipeline whenever the studio
wants opinionated guidance:

    ├── "For mid-century theme, typically use walnut..."
    ├── "This dimension exceeds standard; consider..."
    ├── "Material cost high; suggest alternatives..."
    ├── "Manufacturing lead time: typically 6-8 weeks for this..."
    └── "Cost per unit decreases significantly at volumes >5..."

Pipeline contract — same as every other LLM service:

    INPUT (project state — theme, dimensions, materials, complexity,
           volume, budget, city)
      → INJECT  (theme rule pack, ergonomic ranges, material catalogue
                 with costs/leads, BRD lead-time bands per trade,
                 manufacturer-margin volume tiers, city price index)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (every category is in scope; every cited material /
                   theme / lead-time band is in the catalogue;
                   confidence + impact + effort labels are controlled)
      → OUTPUT  (recommendations JSON conforming to the BRD template)

The service authors a *list* of recommendations — one per BRD bullet
that fires for the supplied project state. The LLM does NOT invent
alternatives — it picks them from the catalogue.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import (
    costing,
    ergonomics,
    manufacturing,
    materials,
    regional_materials,
    themes,
)
from app.services.cost_engine_service import TRADE_HOURS_BY_COMPLEXITY

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None


def _client_instance() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    return _client


# ── Vocabularies ────────────────────────────────────────────────────────────
RECOMMENDATION_CATEGORIES_IN_SCOPE = (
    "theme_material_pairing",      # "for mid-century, typically walnut"
    "dimension_alternative",       # "exceeds ergonomic range; try X"
    "material_alternative",        # "cost high; consider Y instead"
    "manufacturing_lead_time",     # "typically 6–8 weeks for this complexity"
    "volume_economies",            # "per-unit cost falls sharply above 5 units"
    "compliance_alert",            # generic NBC / code call-out
    "supplier_or_region",          # "shift sourcing to lower-index city"
)

CONFIDENCE_LEVELS_IN_SCOPE = ("high", "medium", "low")
IMPACT_LEVELS_IN_SCOPE = ("high", "medium", "low")
EFFORT_LEVELS_IN_SCOPE = ("low", "medium", "high")


# ── Request schema ──────────────────────────────────────────────────────────


class RecommendationsRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    theme: str = Field(default="", max_length=64)
    piece_type: str = Field(default="", max_length=80)
    primary_material: str = Field(default="", max_length=80)
    primary_material_family: str = Field(default="", max_length=32)
    dimensions_m: dict[str, float] = Field(default_factory=dict)
    complexity: str = Field(default="moderate", max_length=32)
    units: int = Field(default=1, ge=1, le=10000)
    city: str = Field(default="", max_length=80)
    budget_inr: float | None = Field(default=None, ge=0)
    notes: str = Field(default="", max_length=600)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _normalise(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_").replace("-", "_")


def _theme_pairing_slice(theme_name: str) -> dict[str, Any]:
    pack = themes.get(theme_name)
    if not pack:
        return {"theme_known": False, "available_themes": themes.list_names()}
    return {
        "theme_known": True,
        "theme": pack.get("display_name") or theme_name,
        "material_palette": pack.get("material_palette") or {},
        "colour_palette": pack.get("colour_palette") or [],
        "signature_moves": pack.get("signature_moves") or [],
        "hardware": pack.get("hardware") or {},
    }


def _material_alternatives_slice(family: str, name: str, *,
                                 city: str | None = None) -> dict[str, Any]:
    fam = _normalise(family)
    n = _normalise(name)
    index = regional_materials.price_index_for_city(city)
    if not isinstance(index, (int, float)):
        index = 1.0

    if fam == "wood":
        chosen = materials.WOOD.get(n) or {}
        candidates = [
            {
                "name": k,
                "cost_inr_kg": v.get("cost_inr_kg"),
                "density_kg_m3": v.get("density_kg_m3"),
                "mor_mpa": v.get("mor_mpa"),
                "moe_mpa": v.get("moe_mpa"),
                "lead_time_weeks": v.get("lead_time_weeks"),
                "scaled_cost_inr_kg": (
                    [round(c * index, 0) for c in (v.get("cost_inr_kg") or (0, 0))]
                    if v.get("cost_inr_kg") else None
                ),
            }
            for k, v in materials.WOOD.items()
        ]
    elif fam == "metal":
        chosen = materials.METALS.get(n) or {}
        candidates = [
            {
                "name": k,
                "cost_inr_kg": v.get("cost_inr_kg"),
                "density_kg_m3": v.get("density_kg_m3"),
                "yield_mpa": v.get("yield_mpa"),
                "scaled_cost_inr_kg": (
                    [round(c * index, 0) for c in (v.get("cost_inr_kg") or (0, 0))]
                    if v.get("cost_inr_kg") else None
                ),
            }
            for k, v in materials.METALS.items()
        ]
    else:
        chosen, candidates = {}, []
    return {
        "family": fam,
        "name": n,
        "chosen": chosen,
        "candidates": candidates,
        "city_price_index_applied": index,
    }


def _lead_time_slice(complexity: str) -> dict[str, Any]:
    c = _normalise(complexity) or "moderate"
    base_band = list(manufacturing.LEAD_TIMES_WEEKS.get("woodworking_furniture") or (4, 8))
    high_extension = {
        "simple": 0,
        "moderate": 0,
        "complex": 1,
        "highly_complex": 2,
    }.get(c, 0)
    band = (base_band[0], base_band[1] + high_extension)
    trade_hours = {
        trade: list(table.get(c) or ())
        for trade, table in TRADE_HOURS_BY_COMPLEXITY.items()
    }
    return {
        "complexity": c,
        "woodworking_furniture_band_brd": base_band,
        "this_piece_band_weeks": list(band),
        "trade_hours_band_at_this_complexity": trade_hours,
        "moq_units_brd": manufacturing.MOQ.get("woodworking_small_batch", 1),
    }


def _volume_economies_slice(units: int) -> dict[str, Any]:
    if units <= 1:
        tier = "one_off"
    elif units <= 25:
        tier = "small_batch"
    elif units <= 250:
        tier = "production"
    else:
        tier = "mass_production"
    band = costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.get(tier) or (40.0, 55.0)
    ladder = [
        {"tier": k, "band_pct": list(v)}
        for k, v in costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.items()
    ]
    return {
        "units": units,
        "current_tier": tier,
        "current_margin_band_pct": list(band),
        "tier_ladder": ladder,
        "next_tier_unit_threshold": {
            "one_off_to_small_batch": 2,
            "small_batch_to_production": 26,
            "production_to_mass_production": 251,
        },
    }


def _ergo_band_slice(piece_type: str, dimensions_m: dict[str, float]) -> dict[str, Any]:
    """Find ergonomic bands relevant to this piece type + flag any input outside band."""
    pt = _normalise(piece_type)
    table_map = {
        "chair": ergonomics.CHAIRS,
        "dining_chair": ergonomics.CHAIRS,
        "lounge_chair": ergonomics.CHAIRS,
        "office_chair": ergonomics.CHAIRS,
        "armchair": ergonomics.CHAIRS,
        "table": ergonomics.TABLES,
        "dining_table": ergonomics.TABLES,
        "coffee_table": ergonomics.TABLES,
        "bed": ergonomics.BEDS,
        "wardrobe": ergonomics.STORAGE,
        "bookshelf": ergonomics.STORAGE,
        "cabinet": ergonomics.STORAGE,
    }
    table = table_map.get(pt)
    if not table:
        return {"piece_type": pt, "ergonomic_bands": None, "issues": []}
    item_key = pt if pt in table else next(iter(table.keys()))
    spec = table.get(item_key) or {}
    ranges = {k: list(v) for k, v in spec.items() if isinstance(v, tuple)}

    # Map provided dims onto band keys (mm).
    given_mm = {}
    for axis in ("length", "width", "height"):
        v = dimensions_m.get(axis)
        if v is not None:
            given_mm[f"{axis}_mm"] = float(v) * 1000.0
    issues = []
    for dim_key, value in given_mm.items():
        band = ranges.get(dim_key)
        if band:
            lo, hi = band
            if value < lo:
                issues.append({"dim": dim_key, "value_mm": value, "band_mm": [lo, hi], "status": "warn_low"})
            elif value > hi:
                issues.append({"dim": dim_key, "value_mm": value, "band_mm": [lo, hi], "status": "warn_high"})
    return {
        "piece_type": pt,
        "ergo_item_key": item_key,
        "ergonomic_bands_mm": ranges,
        "given_mm": given_mm,
        "issues": issues,
    }


def build_recommendations_knowledge(req: RecommendationsRequest) -> dict[str, Any]:
    return {
        "project": {
            "name": req.project_name,
            "theme": req.theme or None,
            "piece_type": req.piece_type or None,
            "primary_material_family": req.primary_material_family or None,
            "primary_material": req.primary_material or None,
            "dimensions_m": req.dimensions_m or {},
            "complexity": req.complexity,
            "units": req.units,
            "city": req.city or None,
            "budget_inr": req.budget_inr,
            "notes": req.notes or None,
        },
        "theme_pairing": _theme_pairing_slice(req.theme) if req.theme else {},
        "material_alternatives": (
            _material_alternatives_slice(
                req.primary_material_family, req.primary_material, city=req.city,
            ) if req.primary_material_family and req.primary_material else {}
        ),
        "ergo": (
            _ergo_band_slice(req.piece_type, req.dimensions_m or {})
            if req.piece_type else {}
        ),
        "lead_time": _lead_time_slice(req.complexity),
        "volume": _volume_economies_slice(req.units),
        "city_price_index": regional_materials.price_index_for_city(req.city) or 1.0,
        "vocab": {
            "categories_in_scope": list(RECOMMENDATION_CATEGORIES_IN_SCOPE),
            "confidence_levels": list(CONFIDENCE_LEVELS_IN_SCOPE),
            "impact_levels": list(IMPACT_LEVELS_IN_SCOPE),
            "effort_levels": list(EFFORT_LEVELS_IN_SCOPE),
            "themes_known": themes.list_names(),
            "wood_species_known": sorted(list(materials.WOOD.keys())),
            "metals_known": sorted(list(materials.METALS.keys())),
            "complexity_levels": ["simple", "moderate", "complex", "highly_complex"],
            "volume_tiers": list(costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.keys()),
            "cities_known": sorted(list(regional_materials.CITY_PRICE_INDEX.keys())),
        },
    }


# ── System prompt ───────────────────────────────────────────────────────────


RECOMMENDATIONS_SYSTEM_PROMPT = """You are a senior studio principal authoring a *Recommendations Report* (BRD Layer 6) — the opinionated guidance the studio surfaces alongside the design pipeline.

Read the [KNOWLEDGE] block — project state (theme, piece, material, dimensions, complexity, units, city, budget), theme_pairing (rule pack), material_alternatives (catalogue rows with costs scaled by city), ergo (ergonomic bands + any out-of-band dim), lead_time (BRD bands per trade × complexity), volume (current tier + ladder), and the controlled vocabulary — and produce a structured recommendations JSON.

Studio voice — short, decisive, no marketing prose. The deterministic helpers already pulled the slice; your job is to PICK the recommendations that fire for this project state, RANK them by impact, and CITE the BRD numbers verbatim.

Hard rules for header:
- categories_used MUST be a subset of vocab.categories_in_scope.

Hard rules for recommendations[] (one per BRD bullet that applies; 3–6 items typical):
- category MUST be in vocab.categories_in_scope.
- title is one short sentence — verbatim shape ("For mid-century theme, typically use walnut…").
- detail is 1–2 sentences with cited numbers from the knowledge slice; never invent.
- supporting[] cites the data points used: each entry has 'source' (knowledge module path, e.g. 'themes.mid_century_modern.material_palette', 'materials.WOOD.walnut.cost_inr_kg', 'manufacturing.LEAD_TIMES_WEEKS.woodworking_furniture') and 'value' (stringified band / number).
- alternatives[] (only for material_alternative / dimension_alternative): 1–4 picks from the catalogue. Each carries 'name' (must be in vocab.wood_species_known / metals_known / theme palette / ergo band keys) and 'why' (one short sentence).
- confidence MUST be in vocab.confidence_levels.
- impact MUST be in vocab.impact_levels.
- effort MUST be in vocab.effort_levels.

Hard rules for category coverage:
- If theme_pairing.theme_known: emit a 'theme_material_pairing' rec citing material_palette + signature_moves.
- If ergo.issues is non-empty: emit a 'dimension_alternative' rec for each issue, with the band + a midpoint suggestion.
- If material_alternatives.candidates has >2 entries with cost_inr_kg below the chosen one's cost_inr_kg.high: emit a 'material_alternative' rec with up to 3 alternatives.
- ALWAYS emit a 'manufacturing_lead_time' rec citing lead_time.this_piece_band_weeks + the trade-hours band that drives it.
- ALWAYS emit a 'volume_economies' rec citing volume.current_tier + next_tier_unit_threshold.
- Emit a 'supplier_or_region' rec ONLY when project.city is set and city_price_index > 1.05 — propose a lower-index city for sourcing with the index delta.

ranking[] is the recommendation indices in priority order, highest impact first.

assumptions[] cites every default used (e.g. 'defaulted complexity to moderate', 'budget not provided — recommendations not gated on cost ceiling').

Never invent BRD numbers. Snap every value to the catalogue."""


# ── JSON schema ─────────────────────────────────────────────────────────────


def _supporting_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "value": {"type": "string"},
        },
        "required": ["source", "value"],
        "additionalProperties": False,
    }


def _alternative_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "why": {"type": "string"},
        },
        "required": ["name", "why"],
        "additionalProperties": False,
    }


def _recommendation_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "category": {"type": "string"},
            "title": {"type": "string"},
            "detail": {"type": "string"},
            "supporting": {"type": "array", "items": _supporting_schema()},
            "alternatives": {"type": "array", "items": _alternative_schema()},
            "confidence": {"type": "string"},
            "impact": {"type": "string"},
            "effort": {"type": "string"},
        },
        "required": [
            "category", "title", "detail", "supporting",
            "alternatives", "confidence", "impact", "effort",
        ],
        "additionalProperties": False,
    }


RECOMMENDATIONS_SCHEMA: dict[str, Any] = {
    "name": "recommendations",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "theme": {"type": "string"},
                    "piece_type": {"type": "string"},
                    "city": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "categories_used": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "rec_count": {"type": "integer"},
                },
                "required": [
                    "project", "theme", "piece_type", "city",
                    "date_iso", "categories_used", "rec_count",
                ],
                "additionalProperties": False,
            },
            "recommendations": {
                "type": "array",
                "items": _recommendation_schema(),
            },
            "ranking": {
                "type": "array",
                "items": {"type": "integer"},
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["header", "recommendations", "ranking", "assumptions"],
        "additionalProperties": False,
    },
}


def _user_message(req: RecommendationsRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Theme: {req.theme or '(not specified)'}\n"
        f"- Piece type: {req.piece_type or '(not specified)'}\n"
        f"- Material: {req.primary_material_family or '?'}/{req.primary_material or '?'}\n"
        f"- Dimensions (m): {req.dimensions_m}\n"
        f"- Complexity: {req.complexity}\n"
        f"- Units: {req.units}\n"
        f"- City: {req.city or '(not specified)'}\n"
        f"- Budget INR: {req.budget_inr if req.budget_inr is not None else '(not specified)'}\n"
        f"- Date (UTC ISO): {today}\n\n"
        "Produce the recommendations JSON. Pick categories that fire from the "
        "deterministic slice; cite values verbatim; suggest alternatives only "
        "from the catalogue; rank by impact."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    vocab = knowledge.get("vocab") or {}
    categories = set(vocab.get("categories_in_scope") or [])
    confidences = set(vocab.get("confidence_levels") or [])
    impacts = set(vocab.get("impact_levels") or [])
    efforts = set(vocab.get("effort_levels") or [])
    woods = set(vocab.get("wood_species_known") or [])
    metals = set(vocab.get("metals_known") or [])
    themes_known = set(vocab.get("themes_known") or [])

    out: dict[str, list[Any]] = {
        "bad_category": [],
        "bad_confidence": [],
        "bad_impact": [],
        "bad_effort": [],
        "bad_alternative_name": [],
        "header_categories_extra": [],
        "header_categories_missing": [],
        "missing_lead_time_rec": [],
        "missing_volume_rec": [],
        "ranking_out_of_range": [],
    }

    recs = spec.get("recommendations") or []
    used_categories: set[str] = set()
    for i, rec in enumerate(recs):
        cat = rec.get("category")
        if cat not in categories:
            out["bad_category"].append({"index": i, "value": cat})
        else:
            used_categories.add(cat)
        for fld, allowed, bucket in (
            ("confidence", confidences, "bad_confidence"),
            ("impact", impacts, "bad_impact"),
            ("effort", efforts, "bad_effort"),
        ):
            v = (rec.get(fld) or "").lower()
            if v not in allowed:
                out[bucket].append({"index": i, "value": rec.get(fld)})
        # Alternatives must reference catalogue entries when category demands it.
        if cat == "material_alternative":
            for alt in rec.get("alternatives") or []:
                name = _normalise(alt.get("name", ""))
                if name not in woods and name not in metals:
                    out["bad_alternative_name"].append({
                        "index": i, "name": alt.get("name"),
                    })

    # Header categories_used must equal the set used in recs.
    header = spec.get("header") or {}
    declared_cats = set(header.get("categories_used") or [])
    extras = declared_cats - used_categories
    missing = used_categories - declared_cats
    if extras:
        out["header_categories_extra"].extend(sorted(extras))
    if missing:
        out["header_categories_missing"].extend(sorted(missing))

    # Lead time + volume are mandatory.
    if "manufacturing_lead_time" not in used_categories:
        out["missing_lead_time_rec"].append(True)
    if "volume_economies" not in used_categories:
        out["missing_volume_rec"].append(True)

    # Ranking indices must reference real recommendations.
    ranking = spec.get("ranking") or []
    for r in ranking:
        if not isinstance(r, int) or r < 0 or r >= len(recs):
            out["ranking_out_of_range"].append(r)

    return {
        "categories_in_scope": not out["bad_category"],
        "bad_category": out["bad_category"],
        "confidences_valid": not out["bad_confidence"],
        "bad_confidence": out["bad_confidence"],
        "impacts_valid": not out["bad_impact"],
        "bad_impact": out["bad_impact"],
        "efforts_valid": not out["bad_effort"],
        "bad_effort": out["bad_effort"],
        "alternative_names_in_catalogue": not out["bad_alternative_name"],
        "bad_alternative_name": out["bad_alternative_name"],
        "header_categories_match_recs": (
            not out["header_categories_extra"] and not out["header_categories_missing"]
        ),
        "header_categories_extra": out["header_categories_extra"],
        "header_categories_missing": out["header_categories_missing"],
        "lead_time_rec_present": not out["missing_lead_time_rec"],
        "volume_rec_present": not out["missing_volume_rec"],
        "ranking_indices_valid": not out["ranking_out_of_range"],
        "ranking_out_of_range": out["ranking_out_of_range"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class RecommendationsError(RuntimeError):
    """Raised when the LLM recommendations stage cannot produce a grounded sheet."""


async def generate_recommendations(req: RecommendationsRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise RecommendationsError(
            "OpenAI API key is not configured. The recommendations stage "
            "requires a live LLM call; no static fallback is served."
        )

    knowledge = build_recommendations_knowledge(req)
    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": RECOMMENDATIONS_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": RECOMMENDATIONS_SCHEMA,
            },
            temperature=0.25,
            max_tokens=2000,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for recommendations")
        raise RecommendationsError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RecommendationsError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)
    return {
        "id": "recommendations",
        "name": "Recommendations Report",
        "model": settings.openai_model,
        "knowledge": knowledge,
        "recommendations": spec,
        "validation": validation,
    }
