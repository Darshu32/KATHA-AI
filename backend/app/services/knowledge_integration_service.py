"""Knowledge Integration Service (BRD Layer 6).

Where the BRD knowledge automatically applies during DESIGN GENERATION.
A single endpoint per event type — the UI / pipeline fires one of:

    theme_selected      → applies proportions, materials, colours
    space_input         → checks against architectural standards
    dimension_input     → compares against ergonomic ranges
    material_selected   → auto-applies technical properties

…and the service returns a *knowledge application report*: the
deterministic slice that auto-applies + the LLM's narrative explaining
which BRD rule fires, what it means for the design, and what to fill
next.

Pipeline contract — same as every other LLM service in the project:

    INPUT (event kind + event payload + optional project context)
      → INJECT  (deterministic slice from app.knowledge.* — theme rule
                 pack, space standards, ergonomic ranges, material
                 catalogue rows; plus checks already run by helpers)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (every cited rule is in the catalogue; status flags
                   match the deterministic checks; suggestions point
                   at fields the schema actually exposes)
      → OUTPUT  (knowledge_application JSON conforming to the BRD
                 template)
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
    clearances,
    codes,
    costing,
    ergonomics,
    ibc,
    manufacturing,
    materials,
    mep,
    regional_materials,
    space_standards,
    structural,
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
EVENT_KINDS_IN_SCOPE = (
    # BRD Layer 6 — DESIGN GENERATION events.
    "theme_selected",
    "space_input",
    "dimension_input",
    "material_selected",
    # BRD Layer 6 — SPECIFICATION GENERATION events.
    "dimensions_quantities",     # auto-calculates quantity from L×W×H + density
    "joint_selected",            # auto-applies joinery tolerances
    "finish_selected",           # auto-determines prep steps + cost
    "manufacturing_complexity",  # auto-assigns complexity tier from parametric inputs
    # BRD Layer 6 — COST CALCULATION events.
    "complexity_labor_hours",    # complexity tier → hours band per trade × labor rates
    "location_index",            # city → price index + rate-band scaling
    "volume_economies",          # unit count → volume tier + margin band + per-unit cost trend
    # BRD Layer 6 — QUALITY ASSURANCE events.
    "dimensions_vs_standards",   # holistic check: ergonomic + space-standard + NBC dims
    "load_calculations",         # span + live/dead load → structural viability
    "building_codes",            # NBC + IBC compliance flags for a room/space
    "manufacturing_feasibility", # tolerance vs BRD band; flag if too tight
    "cost_reasonableness",       # estimate vs expected band → high/low/ok flag
)
QUANTITY_BASIS_IN_SCOPE = ("kg", "m2", "m3", "linear_m", "piece")
COMPLEXITY_LEVELS_IN_SCOPE = ("simple", "moderate", "complex", "highly_complex")
SEGMENTS_IN_SCOPE = ("residential", "commercial", "hospitality")
ERGO_CATEGORIES_IN_SCOPE = ("chair", "table", "bed", "storage")
MATERIAL_FAMILIES_IN_SCOPE = ("wood", "metal", "fabric", "stone", "glass", "finish")
STATUS_IN_SCOPE = ("ok", "warn_low", "warn_high", "info", "unknown", "error")


# ── Deterministic event handlers (the "auto-applies" slice) ─────────────────


def _normalise(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _theme_application(name: str) -> dict[str, Any]:
    pack = themes.get(name)
    if not pack:
        return {
            "status": "unknown",
            "message": f"Theme '{name}' not in catalogue.",
            "available": themes.list_names(),
        }
    return {
        "status": "ok",
        "theme": pack.get("display_name") or name,
        "auto_applied": {
            "proportions": pack.get("proportions") or {},
            "material_palette": pack.get("material_palette") or {},
            "colour_palette": pack.get("colour_palette") or [],
            "signature_moves": pack.get("signature_moves") or [],
            "hardware": pack.get("hardware") or {},
            "material_pattern": pack.get("material_pattern") or {},
        },
    }


def _space_application(room_type: str, area_m2: float | None,
                       segment: str) -> dict[str, Any]:
    seg = _normalise(segment) or "residential"
    rt = _normalise(room_type)
    table = {
        "residential": space_standards.RESIDENTIAL,
        "commercial":  space_standards.COMMERCIAL,
        "hospitality": space_standards.HOSPITALITY,
    }.get(seg, space_standards.RESIDENTIAL)

    standard = table.get(rt)
    if not standard:
        return {
            "status": "unknown",
            "message": f"No {seg} standard for room type '{room_type}'.",
            "available": sorted(list(table.keys())),
        }

    check = (
        space_standards.area_check(rt, float(area_m2), seg)
        if area_m2 is not None else
        {"status": "info", "message": "No area provided — minimum standards listed below."}
    )
    ach = mep.AIR_CHANGES_PER_HOUR.get(rt)
    return {
        "status": check.get("status", "info"),
        "segment": seg,
        "room_type": rt,
        "auto_applied": {
            "min_area_m2": standard.get("min_area_m2"),
            "typical_area_m2": standard.get("typical_area_m2"),
            "max_typical_m2": standard.get("max_typical_m2"),
            "min_dimension_m": standard.get("min_dimension_m"),
            "typical_ceiling_m": standard.get("typical_ceiling_m"),
            "code_notes": standard.get("notes"),
            "ach_recommended": ach,
        },
        "check": check,
    }


def _dimension_application(category: str, item: str,
                            dim: str, value_mm: float | None) -> dict[str, Any]:
    cat = _normalise(category)
    it = _normalise(item)
    d = _normalise(dim)
    table_map = {
        "chair": ergonomics.CHAIRS,
        "table": ergonomics.TABLES,
        "bed":   ergonomics.BEDS,
        "storage": ergonomics.STORAGE,
    }
    table = table_map.get(cat)
    if table is None:
        return {
            "status": "unknown",
            "message": f"Unknown ergonomic category '{category}'.",
            "available": list(table_map.keys()),
        }
    spec = table.get(it)
    if not spec:
        return {
            "status": "unknown",
            "message": f"No ergonomic range for {cat}/{it}.",
            "available": sorted(list(table.keys())),
        }
    if value_mm is None:
        return {
            "status": "info",
            "message": "No value provided — band listed below.",
            "auto_applied": {
                "category": cat, "item": it, "dim": d,
                "ranges_mm": {k: v for k, v in spec.items() if isinstance(v, tuple)},
            },
        }
    check = ergonomics.check_range(cat, it, d, float(value_mm))
    return {
        "status": check.get("status", "info"),
        "category": cat,
        "item": it,
        "dim": d,
        "value_mm": float(value_mm),
        "auto_applied": {
            "ranges_mm": {k: v for k, v in spec.items() if isinstance(v, tuple)},
        },
        "check": check,
    }


def _material_application(family: str, name: str) -> dict[str, Any]:
    fam = _normalise(family)
    n = _normalise(name)
    if fam not in MATERIAL_FAMILIES_IN_SCOPE:
        return {
            "status": "unknown",
            "message": f"Unknown material family '{family}'.",
            "available": list(MATERIAL_FAMILIES_IN_SCOPE),
        }
    if fam == "wood":
        spec = materials.WOOD.get(n)
        if not spec:
            return {
                "status": "unknown",
                "message": f"Wood species '{name}' not in catalogue.",
                "available": sorted(list(materials.WOOD.keys())),
            }
        return {
            "status": "ok",
            "family": fam,
            "name": n,
            "auto_applied": {
                "density_kg_m3": spec.get("density_kg_m3"),
                "mor_mpa": spec.get("mor_mpa"),
                "moe_mpa": spec.get("moe_mpa"),
                "shrinkage_pct": spec.get("shrinkage_pct"),
                "cost_inr_kg": spec.get("cost_inr_kg"),
                "lead_time_weeks": spec.get("lead_time_weeks"),
                "finish_palette": list(materials.WOOD_BRD_FINISH_PALETTE),
            },
        }
    if fam == "metal":
        spec = materials.METALS.get(n)
        if not spec:
            return {
                "status": "unknown",
                "message": f"Metal '{name}' not in catalogue.",
                "available": sorted(list(materials.METALS.keys())),
            }
        return {
            "status": "ok",
            "family": fam,
            "name": n,
            "auto_applied": {
                "density_kg_m3": spec.get("density_kg_m3"),
                "yield_mpa": spec.get("yield_mpa"),
                "tensile_mpa": spec.get("tensile_mpa"),
                "cost_inr_kg": spec.get("cost_inr_kg"),
                "finish_palette": list(materials.METALS_BRD_FINISH_PALETTE),
                "fabrication_methods": list(materials.METALS_BRD_FABRICATION),
            },
        }
    if fam == "finish":
        spec = materials.FINISHES.get(n)
        if not spec:
            return {
                "status": "unknown",
                "message": f"Finish '{name}' not in catalogue.",
                "available": sorted(list(materials.FINISHES.keys())),
            }
        return {"status": "ok", "family": fam, "name": n, "auto_applied": dict(spec)}
    return {
        "status": "info",
        "family": fam,
        "name": n,
        "message": f"No detailed catalogue rows for family '{fam}' yet — name accepted as free-text.",
    }


# ── BRD Layer 6 — SPECIFICATION GENERATION helpers ─────────────────────────


def _dimensions_quantities_application(family: str, name: str,
                                       length_m: float | None,
                                       width_m: float | None,
                                       height_m: float | None,
                                       basis: str | None = None,
                                       count: int = 1) -> dict[str, Any]:
    """Auto-calculate the quantity needed (kg / m² / m³ / linear m) from L×W×H."""
    fam = _normalise(family)
    n = _normalise(name)
    L = float(length_m) if length_m is not None else None
    W = float(width_m) if width_m is not None else None
    H = float(height_m) if height_m is not None else None
    units = max(int(count or 1), 1)

    # Pick the basis from costing.COST_BASIS_BY_FAMILY when caller didn't specify.
    family_basis_map = {
        "wood":   "kg",       # solids priced per kg via density
        "metal":  "kg",
        "fabric": "m2",
        "leather":"m2",
        "stone":  "m2",
        "glass":  "m2",
        "tile":   "m2",
        "finish": "m2",
        "foam":   "m3",
    }
    selected_basis = _normalise(basis) or family_basis_map.get(fam, "m2")
    if selected_basis not in QUANTITY_BASIS_IN_SCOPE:
        return {
            "status": "unknown",
            "message": f"Unknown basis '{basis}'.",
            "available": list(QUANTITY_BASIS_IN_SCOPE),
        }

    if L is None or W is None:
        return {
            "status": "info",
            "message": "Provide at least length and width.",
            "auto_applied": {"basis": selected_basis},
        }

    area_m2 = L * W
    volume_m3 = area_m2 * (H if H is not None else 0.018)   # default 18 mm sheet
    perimeter_m = 2 * (L + W)

    # Mass (kg) — uses density when family/name resolves to wood or metal.
    density = None
    if fam == "wood":
        spec = materials.WOOD.get(n)
        if spec:
            density = spec.get("density_kg_m3")
    elif fam == "metal":
        spec = materials.METALS.get(n)
        if spec:
            density = spec.get("density_kg_m3")

    quantity_value = None
    quantity_unit = selected_basis
    if selected_basis == "m2":
        quantity_value = area_m2 * units
    elif selected_basis == "m3":
        quantity_value = volume_m3 * units
    elif selected_basis == "linear_m":
        quantity_value = perimeter_m * units
    elif selected_basis == "piece":
        quantity_value = float(units)
    elif selected_basis == "kg":
        if density:
            quantity_value = volume_m3 * density * units
        else:
            return {
                "status": "warn_low",
                "message": (
                    f"No density for {fam}/{n} in catalogue — cannot compute mass. "
                    "Switch basis to m² or m³, or pick a known species/metal."
                ),
                "auto_applied": {
                    "basis_requested": "kg",
                    "area_m2": round(area_m2, 4),
                    "volume_m3": round(volume_m3, 6),
                },
            }

    waste_band = list(costing.WASTE_FACTOR_PCT)   # (10, 15)
    waste_mid = (waste_band[0] + waste_band[1]) / 2.0
    quantity_with_waste = round((quantity_value or 0) * (1 + waste_mid / 100.0), 4)

    return {
        "status": "ok",
        "family": fam,
        "name": n,
        "auto_applied": {
            "length_m": L,
            "width_m": W,
            "height_m": H,
            "count": units,
            "area_m2": round(area_m2, 4),
            "volume_m3": round(volume_m3, 6),
            "perimeter_m": round(perimeter_m, 4),
            "basis": selected_basis,
            "quantity_value": round(quantity_value or 0, 4),
            "quantity_unit": quantity_unit,
            "density_kg_m3": density,
            "waste_factor_pct_band": waste_band,
            "waste_factor_pct_mid": waste_mid,
            "quantity_with_waste": quantity_with_waste,
            "quantity_with_waste_unit": quantity_unit,
        },
    }


def _joint_application(method: str) -> dict[str, Any]:
    """Auto-applies the joinery tolerance / difficulty band."""
    m = _normalise(method)
    spec = manufacturing.JOINERY.get(m)
    if not spec:
        return {
            "status": "unknown",
            "message": f"Joinery method '{method}' not in BRD catalogue.",
            "available": sorted(list(manufacturing.JOINERY.keys())),
        }
    # Map difficulty → complexity hint for downstream lead-time estimation.
    diff = (spec.get("difficulty") or "").lower()
    complexity_hint = {
        "very low": "simple",
        "low":      "simple",
        "medium":   "moderate",
        "high":     "complex",
    }.get(diff, "moderate")
    return {
        "status": "ok",
        "method": m,
        "auto_applied": {
            "tolerance_mm": spec.get("tolerance_mm"),
            "strength": spec.get("strength"),
            "difficulty": spec.get("difficulty"),
            "use": spec.get("use"),
            "global_tolerances_mm": {
                "structural": manufacturing.TOLERANCES.get("structural", {}).get("+-mm"),
                "cosmetic": manufacturing.TOLERANCES.get("cosmetic", {}).get("+-mm"),
            },
            "complexity_hint": complexity_hint,
        },
    }


def _finish_application(name: str, *, area_m2: float | None = None,
                        material_cost_inr: float | None = None) -> dict[str, Any]:
    """Auto-determine preparation steps + total cost band for a finish."""
    n = _normalise(name)
    spec = materials.FINISHES.get(n)
    if not spec:
        return {
            "status": "unknown",
            "message": f"Finish '{name}' not in BRD catalogue.",
            "available": sorted(list(materials.FINISHES.keys())),
        }
    # Preparation sequence per finish family.
    prep_sequences: dict[str, list[str]] = {
        "lacquer_pu":  ["sand_220", "stain", "primer", "lacquer_topcoat", "buff"],
        "melamine":    ["sand_180", "edge_band_prep", "melamine_press"],
        "wax_oil":     ["sand_180", "wax_oil_apply", "buff"],
        "powder_coat": ["degrease", "phosphate", "powder_coat", "cure_at_200c"],
        "anodise":     ["clean", "etch", "anodise_bath", "seal"],
    }
    prep = prep_sequences.get(n, ["sand_180", "topcoat", "buff"])

    # Cost band: ₹/m² × area + (optional) finish_pct_of_material × base material cost.
    cost_inr_m2_band = list(spec.get("cost_inr_m2") or (0, 0))
    band_low_total = None; band_high_total = None
    if area_m2 is not None and area_m2 > 0:
        band_low_total = round(cost_inr_m2_band[0] * float(area_m2), 0)
        band_high_total = round(cost_inr_m2_band[1] * float(area_m2), 0)

    finish_pct_band = list(costing.FINISH_COST_PCT_OF_MATERIAL)   # (15, 25)
    finish_pct_mid = (finish_pct_band[0] + finish_pct_band[1]) / 2.0
    pct_of_material = None
    if material_cost_inr is not None and material_cost_inr > 0:
        pct_of_material = {
            "low": round(material_cost_inr * finish_pct_band[0] / 100.0, 0),
            "mid": round(material_cost_inr * finish_pct_mid / 100.0, 0),
            "high": round(material_cost_inr * finish_pct_band[1] / 100.0, 0),
        }

    return {
        "status": "ok",
        "name": n,
        "auto_applied": {
            "preparation_steps": prep,
            "thickness_microns_band": list(spec.get("thickness_microns") or ()) or None,
            "coats_band": list(spec.get("coats") or ()) or None,
            "cure_temp_c": spec.get("cure_temp_c"),
            "cure_time_min_band": list(spec.get("cure_time_min") or ()) or None,
            "sheen_options": spec.get("sheen") or [],
            "cost_inr_m2_band": cost_inr_m2_band,
            "cost_inr_total_band": (
                {"low": band_low_total, "high": band_high_total}
                if band_low_total is not None else None
            ),
            "finish_pct_of_material_band": finish_pct_band,
            "finish_pct_of_material_mid": finish_pct_mid,
            "cost_as_pct_of_material_inr": pct_of_material,
        },
    }


def _manufacturing_complexity_application(joinery_count: int = 0,
                                          edge_profiles: int = 0,
                                          panel_area_m2: float | None = None,
                                          hardware_piece_count: int = 0,
                                          unique_materials: int = 0) -> dict[str, Any]:
    """Score parametric inputs onto the BRD complexity ladder."""
    score = 0
    score += min(joinery_count, 12) * 1.0
    score += min(edge_profiles, 8) * 1.5
    if panel_area_m2 is not None:
        if panel_area_m2 > 6:
            score += 4
        elif panel_area_m2 > 3:
            score += 2
        elif panel_area_m2 > 1:
            score += 1
    score += min(hardware_piece_count, 30) * 0.4
    score += min(unique_materials, 6) * 1.5

    if score < 6:
        complexity = "simple"
    elif score < 14:
        complexity = "moderate"
    elif score < 26:
        complexity = "complex"
    else:
        complexity = "highly_complex"

    # Pull the woodworking lead-time band for this complexity.
    base_band = list(manufacturing.LEAD_TIMES_WEEKS.get("woodworking_furniture") or (4, 8))
    high_extension = {
        "simple": 0,
        "moderate": 0,
        "complex": 1,
        "highly_complex": 2,
    }[complexity]
    lead_time_low_high = (base_band[0], base_band[1] + high_extension)

    return {
        "status": "ok",
        "auto_applied": {
            "score": round(score, 2),
            "complexity": complexity,
            "complexity_levels_in_scope": list(COMPLEXITY_LEVELS_IN_SCOPE),
            "drivers": {
                "joinery_count": joinery_count,
                "edge_profiles": edge_profiles,
                "panel_area_m2": panel_area_m2,
                "hardware_piece_count": hardware_piece_count,
                "unique_materials": unique_materials,
            },
            "woodworking_lead_time_weeks_brd": base_band,
            "woodworking_lead_time_weeks_for_this_piece": lead_time_low_high,
            "moq_units_brd": manufacturing.MOQ.get("woodworking_small_batch", 1),
        },
    }


# ── BRD Layer 6 — COST CALCULATION helpers ─────────────────────────────────


def _complexity_labor_hours_application(complexity: str, *,
                                        trades: list[str] | None = None,
                                        city: str | None = None) -> dict[str, Any]:
    """Complexity tier → hours band per trade × BRD labor rates."""
    c = _normalise(complexity) or "moderate"
    if c not in COMPLEXITY_LEVELS_IN_SCOPE:
        return {
            "status": "unknown",
            "message": f"Unknown complexity '{complexity}'.",
            "available": list(COMPLEXITY_LEVELS_IN_SCOPE),
        }
    selected_trades = [_normalise(t) for t in (trades or list(TRADE_HOURS_BY_COMPLEXITY.keys()))]
    bad = [t for t in selected_trades if t not in TRADE_HOURS_BY_COMPLEXITY]
    if bad:
        return {
            "status": "unknown",
            "message": f"Unknown trade(s): {bad}.",
            "available": sorted(list(TRADE_HOURS_BY_COMPLEXITY.keys())),
        }
    city_index = regional_materials.price_index_for_city(city)
    if not isinstance(city_index, (int, float)):
        city_index = 1.0

    lines: list[dict] = []
    grand = {"low": 0.0, "mid": 0.0, "high": 0.0}
    for trade in selected_trades:
        hours_band = TRADE_HOURS_BY_COMPLEXITY[trade][c]
        rate_band = costing.LABOR_RATES_INR_PER_HOUR[trade]
        lo_h, hi_h = float(hours_band[0]), float(hours_band[1])
        lo_r, hi_r = float(rate_band[0]), float(rate_band[1])
        mid_h = (lo_h + hi_h) / 2.0
        mid_r = (lo_r + hi_r) / 2.0
        line = {
            "trade": trade,
            "hours_band": [lo_h, hi_h],
            "hours_mid": mid_h,
            "rate_band_inr_hour": [lo_r, hi_r],
            "effective_rate_inr_hour": {
                "low":  round(lo_r * city_index, 0),
                "mid":  round(mid_r * city_index, 0),
                "high": round(hi_r * city_index, 0),
            },
            "subtotal_inr": {
                "low":  round(lo_h * lo_r * city_index, 0),
                "mid":  round(mid_h * mid_r * city_index, 0),
                "high": round(hi_h * hi_r * city_index, 0),
            },
        }
        for k in ("low", "mid", "high"):
            grand[k] += line["subtotal_inr"][k]
        lines.append(line)

    return {
        "status": "ok",
        "complexity": c,
        "auto_applied": {
            "city": city or None,
            "city_price_index": city_index,
            "trades": lines,
            "labor_subtotal_inr": {k: round(v, 0) for k, v in grand.items()},
        },
    }


def _location_index_application(city: str | None) -> dict[str, Any]:
    """City → price index + how it scales every BRD cost band."""
    raw = (city or "").strip()
    key = raw.lower().replace(" ", "_") if raw else None
    if key and key not in regional_materials.CITY_PRICE_INDEX:
        return {
            "status": "unknown",
            "message": f"City '{city}' not in catalogue — defaulting to 1.00 (Tier-1).",
            "auto_applied": {
                "city_input": raw,
                "city_price_index": 1.0,
                "available": sorted(list(regional_materials.CITY_PRICE_INDEX.keys())),
            },
        }
    index = regional_materials.price_index_for_city(key)
    if not isinstance(index, (int, float)):
        index = 1.0
    nearest = sorted(
        regional_materials.CITY_PRICE_INDEX.items(), key=lambda kv: abs(kv[1] - index)
    )[:3]

    # How the index scales each BRD labor rate band.
    labor_scaled: dict[str, dict] = {}
    for trade, (lo, hi) in costing.LABOR_RATES_INR_PER_HOUR.items():
        labor_scaled[trade] = {
            "base_band_inr_hour": [lo, hi],
            "scaled_band_inr_hour": [round(lo * index, 0), round(hi * index, 0)],
        }

    # MEP system cost bands also scale.
    mep_scaled: dict[str, dict] = {}
    for system, spec in mep.SYSTEM_COST_INR_PER_M2.items():
        lo, hi = spec.get("range") or (0, 0)
        mep_scaled[system] = {
            "base_inr_m2": [lo, hi],
            "scaled_inr_m2": [round(lo * index, 0), round(hi * index, 0)],
        }

    return {
        "status": "ok" if key else "info",
        "city": raw or None,
        "auto_applied": {
            "city_price_index": index,
            "labor_rates_scaled": labor_scaled,
            "mep_cost_bands_scaled": mep_scaled,
            "nearest_cities": [{"city": c, "index": v} for c, v in nearest],
            "available_cities": sorted(list(regional_materials.CITY_PRICE_INDEX.keys())),
        },
    }


def _volume_tier_for_units(units: int) -> str:
    if units <= 1:
        return "one_off"
    if units <= 25:
        return "small_batch"
    if units <= 250:
        return "production"
    return "mass_production"


def _volume_economies_application(units: int,
                                  per_unit_manufacturing_cost_inr: float | None = None
                                  ) -> dict[str, Any]:
    """Unit count → volume tier + manufacturer margin band + per-unit cost trend."""
    if units <= 0:
        return {
            "status": "unknown",
            "message": "units must be a positive integer.",
        }
    tier = _volume_tier_for_units(units)
    band = costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.get(tier) or (40.0, 55.0)
    pct_mid = round((band[0] + band[1]) / 2.0, 2)

    # Per-unit cost trend — assume 8 % learning curve adjustment per
    # doubling of units beyond unit 1, capped at 25 % total reduction.
    if per_unit_manufacturing_cost_inr and per_unit_manufacturing_cost_inr > 0:
        import math as _math
        doublings = max(0.0, _math.log2(max(units, 1)))
        reduction = min(0.25, 0.08 * doublings)
        per_unit_adjusted = per_unit_manufacturing_cost_inr * (1 - reduction)
        ex_factory_per_unit = per_unit_adjusted * (1 + pct_mid / 100.0)
        cost_trend = {
            "base_per_unit_inr": round(per_unit_manufacturing_cost_inr, 0),
            "learning_reduction_pct": round(reduction * 100.0, 2),
            "adjusted_per_unit_inr": round(per_unit_adjusted, 0),
            "ex_factory_per_unit_inr": round(ex_factory_per_unit, 0),
            "total_inr": round(ex_factory_per_unit * units, 0),
        }
    else:
        cost_trend = None

    # Tier ladder for context.
    ladder = [
        {"tier": k, "band_pct": list(v)}
        for k, v in costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.items()
    ]

    return {
        "status": "ok",
        "auto_applied": {
            "units": units,
            "volume_tier": tier,
            "manufacturer_margin_band_pct": list(band),
            "manufacturer_margin_pct_mid": pct_mid,
            "tier_ladder": ladder,
            "cost_trend": cost_trend,
        },
    }


# ── BRD Layer 6 — QUALITY ASSURANCE helpers ────────────────────────────────


def _dimensions_vs_standards_application(
    room_type: str | None = None,
    area_m2: float | None = None,
    short_side_m: float | None = None,
    height_m: float | None = None,
    *,
    ergo_category: str | None = None,
    ergo_item: str | None = None,
    ergo_dim: str | None = None,
    ergo_value_mm: float | None = None,
    segment: str = "residential",
) -> dict[str, Any]:
    """Holistic dimension QA — runs space-standard + NBC + (optional) ergonomic checks."""
    issues: list[dict] = []
    info: dict[str, Any] = {}

    if room_type:
        rt = _normalise(room_type)
        seg = _normalise(segment) or "residential"
        space_check = (
            space_standards.area_check(rt, float(area_m2), seg)
            if area_m2 is not None else
            {"status": "info", "message": "No area provided."}
        )
        info["space_standard"] = space_check
        if space_check.get("status", "").startswith("warn"):
            issues.append({
                "code": f"space_standards.{seg}.{rt}",
                "issue": space_check.get("message"),
            })
        # NBC check.
        if (area_m2 is not None and short_side_m is not None and height_m is not None):
            nbc = codes.check_room_against_nbc(rt, float(area_m2),
                                                float(short_side_m), float(height_m))
            info["nbc_findings"] = nbc
            for n in nbc:
                issues.append(n)

    if ergo_category and ergo_item and ergo_dim and ergo_value_mm is not None:
        ergo_check = ergonomics.check_range(
            ergo_category, ergo_item, ergo_dim, float(ergo_value_mm)
        )
        info["ergonomic"] = ergo_check
        if ergo_check.get("status", "").startswith("warn"):
            issues.append({
                "code": f"ergonomics.{ergo_category}.{ergo_item}.{ergo_dim}",
                "issue": ergo_check.get("message"),
            })

    if not info:
        return {
            "status": "info",
            "message": "Provide room_type+dims OR ergonomic category/item/dim/value.",
        }
    status = "warn_high" if issues else "ok"
    return {
        "status": status,
        "auto_applied": {
            "checks_run": list(info.keys()),
            "details": info,
            "issues": issues,
        },
    }


def _load_calculations_application(
    *,
    use_type: str | None = None,
    area_m2: float | None = None,
    span_m: float | None = None,
    span_material: str | None = None,
    floor_construction: str | None = None,
) -> dict[str, Any]:
    """Quick structural viability — live/dead load × area + span check."""
    out: dict[str, Any] = {}
    issues: list[str] = []

    use = _normalise(use_type) if use_type else None
    if use and area_m2 is not None:
        live = structural.LIVE_LOADS_KN_PER_M2.get(use)
        if live is None:
            return {
                "status": "unknown",
                "message": f"No live-load row for use_type '{use_type}'.",
                "available": sorted(list(structural.LIVE_LOADS_KN_PER_M2.keys())),
            }
        dead_default = (
            structural.DEAD_LOADS_KN_PER_M2.get(_normalise(floor_construction or ""))
            or structural.DEAD_LOADS_KN_PER_M2.get("rcc_slab_150")
            or 3.5
        )
        total_kn_m2 = live + dead_default
        out["live_load_kn_m2"] = live
        out["dead_load_kn_m2"] = dead_default
        out["total_load_kn_m2"] = round(total_kn_m2, 2)
        out["total_load_kn_for_area"] = round(total_kn_m2 * float(area_m2), 2)

    if span_m is not None and span_material:
        check = structural.check_span(_normalise(span_material), float(span_m))
        out["span_check"] = check
        if check.get("status", "").startswith("warn"):
            issues.append(check.get("message", ""))

    if not out:
        return {
            "status": "info",
            "message": "Provide use_type+area_m2 (load) and/or span_m+span_material (span check).",
        }
    status = "warn_high" if issues else "ok"
    return {
        "status": status,
        "auto_applied": {
            "calculations": out,
            "issues": issues,
            "code_references": [
                "IS 875 Part 1/2 (loads, India)",
                "IBC 2021 §1607 live-load table",
            ],
        },
    }


def _building_codes_application(
    *,
    room_type: str | None = None,
    area_m2: float | None = None,
    short_side_m: float | None = None,
    height_m: float | None = None,
    occupancy_group: str | None = None,
    occupant_load: int | None = None,
) -> dict[str, Any]:
    """NBC + IBC compliance flags for a single space."""
    findings: list[dict] = []

    if room_type and area_m2 is not None and short_side_m is not None and height_m is not None:
        rt = _normalise(room_type)
        nbc_issues = codes.check_room_against_nbc(
            rt, float(area_m2), float(short_side_m), float(height_m)
        )
        findings.extend(nbc_issues)

    occ_data = None
    occ_key_used = None
    if occupancy_group:
        # IBC keys are case-significant single letters (A / B / E / F …);
        # try the raw input first, then upper-case, then normalised.
        for candidate in (
            occupancy_group,
            occupancy_group.strip().upper(),
            _normalise(occupancy_group),
        ):
            if candidate in ibc.OCCUPANCY_GROUPS:
                occ_key_used = candidate
                occ_data = ibc.OCCUPANCY_GROUPS[candidate]
                break
        if occ_data is None:
            return {
                "status": "unknown",
                "message": f"Unknown IBC occupancy group '{occupancy_group}'.",
                "available": sorted(list(ibc.OCCUPANCY_GROUPS.keys())),
            }

    egress_findings: list[dict] = []
    if occ_data and occupant_load is not None:
        egress = ibc.EGRESS
        # Two-exit rule by occupant load.
        two_exits_min = egress.get("two_exits_required_when_occupants_above")
        if two_exits_min is not None and occupant_load > two_exits_min:
            egress_findings.append({
                "code": "IBC §1006",
                "issue": (
                    f"Occupant load {occupant_load} exceeds {two_exits_min} — "
                    "two means of egress required."
                ),
            })
    findings.extend(egress_findings)

    accessibility_refs = list(codes.ACCESSIBILITY.keys()) if hasattr(codes, "ACCESSIBILITY") else []
    fire_refs = list(codes.FIRE_SAFETY.keys()) if hasattr(codes, "FIRE_SAFETY") else []

    if not findings and not (room_type or occupancy_group):
        return {
            "status": "info",
            "message": "Provide room_type+dims and/or occupancy_group+occupant_load to run code checks.",
        }
    status = "warn_high" if findings else "ok"
    return {
        "status": status,
        "auto_applied": {
            "nbc_findings_count": len(findings),
            "findings": findings,
            "ibc_occupancy": occ_data,
            "occupancy_group_input": occupancy_group,
            "accessibility_refs": accessibility_refs,
            "fire_safety_refs": fire_refs,
            "code_references": [
                "NBC India Part 3 (development plan + minimum room dimensions)",
                "NBC India Part 4 (fire & life safety)",
                "IBC 2021 §1006 (egress count)",
                "IBC 2021 §303 (occupancy classification)",
            ],
        },
    }


_TOLERANCE_FLOORS_MM: dict[str, float] = {
    "woodworking_structural": 1.0,
    "woodworking_cosmetic":   2.0,
    "metal_structural":       1.0,
    "metal_cosmetic":         2.0,
    "joinery":                0.5,    # tightest BRD joinery tolerance
}


def _manufacturing_feasibility_application(
    *,
    requested_tolerance_mm: float | None = None,
    band_key: str | None = None,
    joinery_method: str | None = None,
    bend_thickness_mm: float | None = None,
    bend_radius_mm: float | None = None,
) -> dict[str, Any]:
    """Flag tolerances or bend radii tighter than the BRD allows."""
    issues: list[str] = []
    info: dict[str, Any] = {}

    if requested_tolerance_mm is not None:
        bk = _normalise(band_key) if band_key else None
        floor = _TOLERANCE_FLOORS_MM.get(bk) if bk else None
        if bk and floor is None:
            return {
                "status": "unknown",
                "message": f"Unknown tolerance band_key '{band_key}'.",
                "available": list(_TOLERANCE_FLOORS_MM.keys()),
            }
        floor = floor if floor is not None else min(_TOLERANCE_FLOORS_MM.values())
        info["requested_tolerance_mm"] = requested_tolerance_mm
        info["band_floor_mm"] = floor
        info["band_key"] = bk or "tightest_brd_joinery"
        if requested_tolerance_mm + 1e-6 < floor:
            issues.append(
                f"Requested tolerance {requested_tolerance_mm} mm tighter than "
                f"BRD floor {floor} mm — manufacturing may fail QA gates."
            )

    if joinery_method:
        m = _normalise(joinery_method)
        spec = manufacturing.JOINERY.get(m)
        if not spec:
            return {
                "status": "unknown",
                "message": f"Joinery '{joinery_method}' not in catalogue.",
                "available": sorted(list(manufacturing.JOINERY.keys())),
            }
        info["joinery"] = {
            "method": m,
            "tolerance_mm": spec.get("tolerance_mm"),
            "difficulty": spec.get("difficulty"),
        }
        if requested_tolerance_mm is not None and requested_tolerance_mm + 1e-6 < spec["tolerance_mm"]:
            issues.append(
                f"Tolerance {requested_tolerance_mm} mm is tighter than the "
                f"{m} joinery floor {spec['tolerance_mm']} mm."
            )

    if bend_thickness_mm is not None and bend_radius_mm is not None:
        min_radius = float(bend_thickness_mm) * 2.5
        info["bend_check"] = {
            "thickness_mm": bend_thickness_mm,
            "min_radius_mm": min_radius,
            "rule": manufacturing.BENDING_RULE["rule"],
            "specified_radius_mm": bend_radius_mm,
        }
        if bend_radius_mm + 1e-6 < min_radius:
            issues.append(
                f"Bend radius {bend_radius_mm} mm tighter than BRD floor "
                f"{min_radius} mm (R_min = 2.5 × thickness) — risk of cracking."
            )

    if not info:
        return {
            "status": "info",
            "message": "Provide requested_tolerance_mm + band_key, or joinery_method, or bend_thickness_mm + bend_radius_mm.",
        }
    status = "warn_high" if issues else "ok"
    return {
        "status": status,
        "auto_applied": {
            "checks": info,
            "issues": issues,
            "tolerance_floors_mm": dict(_TOLERANCE_FLOORS_MM),
        },
    }


# Indicative ₹/m² bands per piece type for cost-reasonableness QA.
# Footprint area × this band gives an expected manufacturing-cost band; the
# helper compares the user's estimate against it. Bands are studio rule-of-
# thumb at India Tier-1 baseline; multiplied by city_price_index when given.
PIECE_COST_BAND_INR_PER_M2: dict[str, tuple[int, int]] = {
    "side_table":        (12_000,  35_000),
    "coffee_table":      (15_000,  40_000),
    "dining_table":      (20_000,  60_000),
    "console_table":     (18_000,  50_000),
    "desk":              (18_000,  45_000),
    "chair":             (10_000,  30_000),
    "dining_chair":      (10_000,  28_000),
    "lounge_chair":      (20_000,  60_000),
    "office_chair":      (12_000,  40_000),
    "sofa":              (28_000,  70_000),
    "bed":               (20_000,  55_000),
    "bookshelf":         (18_000,  45_000),
    "wardrobe":          (22_000,  60_000),
    "cabinet":           (20_000,  55_000),
    "tv_unit":           (20_000,  55_000),
    "media_console":     (20_000,  55_000),
}


def _cost_reasonableness_application(
    *,
    piece_type: str | None = None,
    footprint_m2: float | None = None,
    estimated_total_inr: float | None = None,
    city: str | None = None,
) -> dict[str, Any]:
    """Compare an estimate against the studio-rule-of-thumb band for piece type."""
    if not piece_type or footprint_m2 is None or estimated_total_inr is None:
        return {
            "status": "info",
            "message": "Provide piece_type, footprint_m2, and estimated_total_inr.",
            "available_piece_types": sorted(list(PIECE_COST_BAND_INR_PER_M2.keys())),
        }
    pt = _normalise(piece_type)
    band = PIECE_COST_BAND_INR_PER_M2.get(pt)
    if band is None:
        return {
            "status": "unknown",
            "message": f"No cost band for piece_type '{piece_type}'.",
            "available_piece_types": sorted(list(PIECE_COST_BAND_INR_PER_M2.keys())),
        }
    city_index = regional_materials.price_index_for_city(city)
    if not isinstance(city_index, (int, float)):
        city_index = 1.0
    expected_low = round(band[0] * float(footprint_m2) * city_index, 0)
    expected_high = round(band[1] * float(footprint_m2) * city_index, 0)
    expected_mid = round((expected_low + expected_high) / 2.0, 0)

    estimate = float(estimated_total_inr)
    if estimate + 1e-6 < expected_low * 0.85:
        status = "warn_low"
        message = (
            f"Estimate ₹{estimate:,.0f} sits >15 % below the expected band "
            f"₹{expected_low:,.0f}–₹{expected_high:,.0f}. Re-check material rates / labour hours."
        )
    elif estimate > expected_high * 1.15:
        status = "warn_high"
        message = (
            f"Estimate ₹{estimate:,.0f} sits >15 % above the expected band "
            f"₹{expected_low:,.0f}–₹{expected_high:,.0f}. Re-check waste / overhead / margin."
        )
    else:
        status = "ok"
        message = (
            f"Estimate ₹{estimate:,.0f} sits inside the expected band "
            f"₹{expected_low:,.0f}–₹{expected_high:,.0f}."
        )
    return {
        "status": status,
        "message": message,
        "auto_applied": {
            "piece_type": pt,
            "footprint_m2": float(footprint_m2),
            "city": city or None,
            "city_price_index": city_index,
            "rate_band_inr_m2": list(band),
            "expected_total_inr_band": {"low": expected_low, "mid": expected_mid, "high": expected_high},
            "estimated_total_inr": estimate,
            "deviation_pct": round((estimate - expected_mid) / expected_mid * 100, 2),
        },
    }


# ── Request schema ──────────────────────────────────────────────────────────


class KnowledgeIntegrationRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    event_kind: str = Field(description="One of EVENT_KINDS_IN_SCOPE")
    payload: dict[str, Any] = Field(default_factory=dict)
    project_context: dict[str, Any] = Field(default_factory=dict)


# ── Knowledge slice (the "auto-applied" deterministic answer) ───────────────


def build_knowledge_integration_slice(req: KnowledgeIntegrationRequest) -> dict[str, Any]:
    kind = _normalise(req.event_kind)
    payload = req.payload or {}

    if kind == "theme_selected":
        application = _theme_application(payload.get("theme") or "")
    elif kind == "space_input":
        application = _space_application(
            payload.get("room_type") or "",
            payload.get("area_m2"),
            payload.get("segment") or "residential",
        )
    elif kind == "dimension_input":
        application = _dimension_application(
            payload.get("category") or "",
            payload.get("item") or "",
            payload.get("dim") or "",
            payload.get("value_mm"),
        )
    elif kind == "material_selected":
        application = _material_application(
            payload.get("family") or "",
            payload.get("name") or "",
        )
    elif kind == "dimensions_quantities":
        application = _dimensions_quantities_application(
            payload.get("family") or "",
            payload.get("name") or "",
            payload.get("length_m"),
            payload.get("width_m"),
            payload.get("height_m"),
            basis=payload.get("basis"),
            count=int(payload.get("count") or 1),
        )
    elif kind == "joint_selected":
        application = _joint_application(payload.get("method") or "")
    elif kind == "finish_selected":
        application = _finish_application(
            payload.get("name") or "",
            area_m2=payload.get("area_m2"),
            material_cost_inr=payload.get("material_cost_inr"),
        )
    elif kind == "manufacturing_complexity":
        application = _manufacturing_complexity_application(
            joinery_count=int(payload.get("joinery_count") or 0),
            edge_profiles=int(payload.get("edge_profiles") or 0),
            panel_area_m2=payload.get("panel_area_m2"),
            hardware_piece_count=int(payload.get("hardware_piece_count") or 0),
            unique_materials=int(payload.get("unique_materials") or 0),
        )
    elif kind == "complexity_labor_hours":
        application = _complexity_labor_hours_application(
            payload.get("complexity") or "moderate",
            trades=payload.get("trades"),
            city=payload.get("city"),
        )
    elif kind == "location_index":
        application = _location_index_application(payload.get("city"))
    elif kind == "volume_economies":
        application = _volume_economies_application(
            int(payload.get("units") or 1),
            per_unit_manufacturing_cost_inr=payload.get("per_unit_manufacturing_cost_inr"),
        )
    elif kind == "dimensions_vs_standards":
        application = _dimensions_vs_standards_application(
            room_type=payload.get("room_type"),
            area_m2=payload.get("area_m2"),
            short_side_m=payload.get("short_side_m"),
            height_m=payload.get("height_m"),
            ergo_category=payload.get("ergo_category"),
            ergo_item=payload.get("ergo_item"),
            ergo_dim=payload.get("ergo_dim"),
            ergo_value_mm=payload.get("ergo_value_mm"),
            segment=payload.get("segment") or "residential",
        )
    elif kind == "load_calculations":
        application = _load_calculations_application(
            use_type=payload.get("use_type"),
            area_m2=payload.get("area_m2"),
            span_m=payload.get("span_m"),
            span_material=payload.get("span_material"),
            floor_construction=payload.get("floor_construction"),
        )
    elif kind == "building_codes":
        application = _building_codes_application(
            room_type=payload.get("room_type"),
            area_m2=payload.get("area_m2"),
            short_side_m=payload.get("short_side_m"),
            height_m=payload.get("height_m"),
            occupancy_group=payload.get("occupancy_group"),
            occupant_load=payload.get("occupant_load"),
        )
    elif kind == "manufacturing_feasibility":
        application = _manufacturing_feasibility_application(
            requested_tolerance_mm=payload.get("requested_tolerance_mm"),
            band_key=payload.get("band_key"),
            joinery_method=payload.get("joinery_method"),
            bend_thickness_mm=payload.get("bend_thickness_mm"),
            bend_radius_mm=payload.get("bend_radius_mm"),
        )
    elif kind == "cost_reasonableness":
        application = _cost_reasonableness_application(
            piece_type=payload.get("piece_type"),
            footprint_m2=payload.get("footprint_m2"),
            estimated_total_inr=payload.get("estimated_total_inr"),
            city=payload.get("city"),
        )
    else:
        application = {
            "status": "error",
            "message": f"Unknown event_kind '{req.event_kind}'.",
            "available": list(EVENT_KINDS_IN_SCOPE),
        }

    return {
        "project": {
            "name": req.project_name,
            "event_kind": kind,
            "payload": payload,
        },
        "application": application,
        "vocab": {
            "event_kinds_in_scope": list(EVENT_KINDS_IN_SCOPE),
            "segments_in_scope": list(SEGMENTS_IN_SCOPE),
            "ergo_categories_in_scope": list(ERGO_CATEGORIES_IN_SCOPE),
            "material_families_in_scope": list(MATERIAL_FAMILIES_IN_SCOPE),
            "status_in_scope": list(STATUS_IN_SCOPE),
            "themes_known": themes.list_names(),
            "room_types_residential": sorted(list(space_standards.RESIDENTIAL.keys())),
            "room_types_commercial": sorted(list(space_standards.COMMERCIAL.keys())),
            "room_types_hospitality": sorted(list(space_standards.HOSPITALITY.keys())),
            "wood_species_known": sorted(list(materials.WOOD.keys())),
            "metals_known": sorted(list(materials.METALS.keys())),
            "finishes_known": sorted(list(materials.FINISHES.keys())),
            "ergo_chairs_known": sorted(list(ergonomics.CHAIRS.keys())),
            "ergo_tables_known": sorted(list(ergonomics.TABLES.keys())),
            "ergo_beds_known": sorted(list(ergonomics.BEDS.keys())),
            "ergo_storage_known": sorted(list(ergonomics.STORAGE.keys())),
            "joinery_methods_known": sorted(list(manufacturing.JOINERY.keys())),
            "complexity_levels_in_scope": list(COMPLEXITY_LEVELS_IN_SCOPE),
            "quantity_basis_in_scope": list(QUANTITY_BASIS_IN_SCOPE),
            "waste_factor_pct_band_brd": list(costing.WASTE_FACTOR_PCT),
            "finish_pct_of_material_brd": list(costing.FINISH_COST_PCT_OF_MATERIAL),
            "labor_trades_known": sorted(list(costing.LABOR_RATES_INR_PER_HOUR.keys())),
            "labor_rates_inr_hour_brd": {
                k: list(v) for k, v in costing.LABOR_RATES_INR_PER_HOUR.items()
            },
            "cities_known": sorted(list(regional_materials.CITY_PRICE_INDEX.keys())),
            "volume_tiers_known": list(costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.keys()),
            "load_use_types_known": sorted(list(structural.LIVE_LOADS_KN_PER_M2.keys())),
            "span_materials_known": sorted(list(structural.SPAN_LIMITS_M.keys())),
            "ibc_occupancy_groups_known": sorted(list(ibc.OCCUPANCY_GROUPS.keys())),
            "tolerance_band_keys_known": list(_TOLERANCE_FLOORS_MM.keys()),
            "piece_types_with_cost_band": sorted(list(PIECE_COST_BAND_INR_PER_M2.keys())),
        },
        "context_summary": {
            "room": (req.project_context or {}).get("room"),
            "style": (req.project_context or {}).get("style"),
            "material_count": len((req.project_context or {}).get("materials") or []),
            "object_count": len((req.project_context or {}).get("objects") or []),
        },
    }


# ── System prompt ───────────────────────────────────────────────────────────


KNOWLEDGE_INTEGRATION_SYSTEM_PROMPT = """You are a senior studio principal authoring a *Knowledge Application Report* (BRD Layer 6) — the message that fires every time the design pipeline ingests a new event (theme picked, space typed, dimension entered, material chosen).

Read the [KNOWLEDGE] block — application (the deterministic slice already computed for this event: which BRD rule fires, what auto-applies, the status flag from the helper), vocabularies, and project context — and produce a structured knowledge_application JSON.

Studio voice — short, decisive, no marketing prose. Numbers come from the application slice; your job is to NARRATE which BRD rule applies, EXPLAIN what it implies for the design, and SUGGEST the next inputs the user should provide.

Hard rules for header:
- event_kind MUST equal application.* event from project.event_kind and be in event_kinds_in_scope.
- status MUST equal application.status (or application.check.status when check is present); MUST be in status_in_scope.

Hard rules for rules_applied[]:
- One entry per BRD rule that auto-fired, in priority order.
- Each entry's name is short and human ("Japandi proportion ratio", "Bedroom min area 9 m²", "Chair seat-height band", "Walnut MOR / MOE").
- Each entry's source MUST cite the knowledge module (e.g. "themes.JAPANDI", "space_standards.RESIDENTIAL.bedroom", "ergonomics.CHAIRS.dining", "materials.WOOD.walnut").
- Each entry's value carries the actual data point (e.g. "1:1.618", "9 m²", "420–480 mm", "MOR 119 MPa").

Hard rules for implications[]:
- 2–4 bullets — what this rule means downstream (cost, lead time, MEP draw, structural stress, ergonomic comfort).
- Cite numbers from the application slice; never invent new bands.

Hard rules for warnings[]:
- Surface every status-not-'ok' message verbatim from application or application.check.
- Add a warning when the user-provided value (when present) sits outside the BRD band. Cite the band.

Hard rules for next_suggested_inputs[]:
- 2–4 entries naming the next field the user should fill, with a short reason. Cite the schema field name (e.g. "graph.room.dimensions.height — to validate ceiling clearance against IBC", "graph.materials[*].finish — to lock in cost band").
- For event_kind='theme_selected': prompt for room_type, dimensions, primary species.
- For event_kind='space_input': prompt for ceiling height, occupancy, primary use.
- For event_kind='dimension_input': prompt for the next dim in the same item.
- For event_kind='material_selected': prompt for finish + region (city price index).

assumptions[] cites every band invoked and any default assumed (e.g. defaulted segment to 'residential')."""


# ── JSON schema ─────────────────────────────────────────────────────────────


def _rule_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "source": {"type": "string"},        # knowledge module path
            "value": {"type": "string"},         # always stringified
            "rationale": {"type": "string"},
        },
        "required": ["name", "source", "value", "rationale"],
        "additionalProperties": False,
    }


def _suggestion_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "field": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["field", "reason"],
        "additionalProperties": False,
    }


KNOWLEDGE_INTEGRATION_SCHEMA: dict[str, Any] = {
    "name": "knowledge_application",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "event_kind": {"type": "string"},
                    "status": {"type": "string"},
                    "date_iso": {"type": "string"},
                },
                "required": ["project", "event_kind", "status", "date_iso"],
                "additionalProperties": False,
            },
            "summary": {"type": "string"},
            "rules_applied": {
                "type": "array",
                "items": _rule_schema(),
            },
            "implications": {
                "type": "array",
                "items": {"type": "string"},
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "next_suggested_inputs": {
                "type": "array",
                "items": _suggestion_schema(),
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header", "summary", "rules_applied",
            "implications", "warnings", "next_suggested_inputs",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: KnowledgeIntegrationRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Event kind: {req.event_kind}\n"
        f"- Payload keys: {sorted(list(req.payload.keys()))}\n"
        f"- Date (UTC ISO): {today}\n\n"
        "Produce the knowledge_application JSON. Cite the deterministic "
        "application slice verbatim — never invent BRD bands, ergonomic "
        "ranges, or material properties. Suggest the next concrete inputs."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    application = knowledge.get("application") or {}
    project = knowledge.get("project") or {}
    expected_status = (
        (application.get("check") or {}).get("status")
        or application.get("status")
        or "info"
    )

    out: dict[str, list[Any]] = {
        "bad_event_kind": [],
        "bad_status": [],
        "missing_application_warning": [],
        "header_event_mismatch": [],
        "no_rules_applied": [],
        "no_suggestions": [],
        "bad_suggestion_field": [],
    }

    header = spec.get("header") or {}
    if header.get("event_kind") != project.get("event_kind"):
        out["header_event_mismatch"].append({
            "expected": project.get("event_kind"),
            "actual": header.get("event_kind"),
        })
    if header.get("event_kind") not in EVENT_KINDS_IN_SCOPE:
        out["bad_event_kind"].append(header.get("event_kind"))
    if (header.get("status") or "") != expected_status:
        out["bad_status"].append({
            "expected": expected_status, "actual": header.get("status"),
        })
    if (header.get("status") or "") not in STATUS_IN_SCOPE:
        out["bad_status"].append({
            "actual": header.get("status"),
            "in_scope": list(STATUS_IN_SCOPE),
        })

    # Surface every non-ok message verbatim.
    expected_warnings: list[str] = []
    for blob in (application, application.get("check") or {}):
        if isinstance(blob, dict) and blob.get("status") not in (None, "ok", "info"):
            msg = blob.get("message")
            if msg:
                expected_warnings.append(msg)
    seen_warnings = set(spec.get("warnings") or [])
    for w in expected_warnings:
        if w not in seen_warnings:
            out["missing_application_warning"].append(w)

    # Need at least one rule when status is ok / warn_*.
    if expected_status in ("ok", "warn_low", "warn_high") and not (spec.get("rules_applied") or []):
        out["no_rules_applied"].append(expected_status)

    # Need at least one next-step suggestion.
    if not (spec.get("next_suggested_inputs") or []):
        out["no_suggestions"].append(True)

    # Suggestion field strings should look schema-pathed (contain a dot).
    for s in spec.get("next_suggested_inputs") or []:
        if "." not in (s.get("field") or ""):
            out["bad_suggestion_field"].append(s.get("field") or "<missing>")

    return {
        "event_kind_in_scope": not out["bad_event_kind"],
        "bad_event_kind": out["bad_event_kind"],
        "status_matches_application": not out["bad_status"],
        "bad_status": out["bad_status"],
        "header_event_matches_request": not out["header_event_mismatch"],
        "header_event_mismatch": out["header_event_mismatch"],
        "all_application_warnings_surfaced": not out["missing_application_warning"],
        "missing_application_warning": out["missing_application_warning"],
        "rules_applied_present_when_known": not out["no_rules_applied"],
        "no_rules_applied": out["no_rules_applied"],
        "next_suggested_inputs_present": not out["no_suggestions"],
        "no_suggestions": out["no_suggestions"],
        "suggestion_fields_look_pathed": not out["bad_suggestion_field"],
        "bad_suggestion_field": out["bad_suggestion_field"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class KnowledgeIntegrationError(RuntimeError):
    """Raised when the LLM knowledge-integration stage cannot produce a grounded sheet."""


async def generate_knowledge_application(req: KnowledgeIntegrationRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise KnowledgeIntegrationError(
            "OpenAI API key is not configured. The knowledge integration stage "
            "requires a live LLM call; no static fallback is served."
        )
    if _normalise(req.event_kind) not in EVENT_KINDS_IN_SCOPE:
        raise KnowledgeIntegrationError(
            f"Unknown event_kind '{req.event_kind}'. "
            f"Pick one of: {', '.join(EVENT_KINDS_IN_SCOPE)}."
        )

    knowledge = build_knowledge_integration_slice(req)
    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": KNOWLEDGE_INTEGRATION_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": KNOWLEDGE_INTEGRATION_SCHEMA,
            },
            temperature=0.2,
            max_tokens=1600,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for knowledge integration")
        raise KnowledgeIntegrationError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise KnowledgeIntegrationError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)
    return {
        "id": "knowledge_application",
        "name": "Knowledge Application Report",
        "model": settings.openai_model,
        "knowledge": knowledge,
        "knowledge_application": spec,
        "validation": validation,
    }
