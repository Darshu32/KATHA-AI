"""Structural design guidelines — loads, spans, spacing.

⚠️ STAGE 3E DEPRECATION NOTICE — April 2026
--------------------------------------------
Values migrated to ``building_standards`` (category=``code``,
subcategory=``structural``, jurisdiction=``india_nbc``). DB-backed
async lookups in :mod:`app.services.standards.codes_lookup`
(``get_live_loads_is875``, ``get_seismic_zones``, ``get_span_limits``,
``check_span``, ``get_foundation_by_soil``, ``get_material_strengths``).

DO NOT update values here. Use ``POST /admin/standards/code/<slug>``.

---

Per BRD Layer 1B. All loads in kN/m^2, lengths in metres, stresses in MPa.
Reference standards: IS 875 (loads), IS 456 (concrete), IS 800 (steel),
IS 883 (timber).
"""

from __future__ import annotations

# Live loads (IS 875 Part 2).
LIVE_LOADS_KN_PER_M2: dict[str, float] = {
    "residential_room": 2.0,
    "residential_balcony": 3.0,
    "office_general": 2.5,
    "office_corridor": 4.0,
    "retail_floor": 4.0,
    "assembly_fixed_seating": 4.0,
    "assembly_movable": 5.0,
    "hotel_room": 2.0,
    "restaurant": 4.0,
    "warehouse_light": 5.0,
    "warehouse_heavy": 10.0,
    "parking_light_vehicles": 4.0,
    "staircase_residential": 3.0,
    "staircase_public": 5.0,
    "roof_accessible": 1.5,
    "roof_inaccessible": 0.75,
}

# Dead loads (typical, kN/m^2).
DEAD_LOADS_KN_PER_M2: dict[str, float] = {
    "rcc_slab_150mm": 3.75,
    "rcc_slab_200mm": 5.0,
    "waterproofing_finishes": 1.5,
    "brick_wall_230mm": 4.6,       # per m height
    "brick_wall_115mm": 2.3,
    "false_ceiling": 0.3,
    "flooring_tile_20mm": 0.5,
    "flooring_marble_25mm": 0.7,
}

# Wind & seismic (indicative — real projects need IS 875 Pt 3 / IS 1893).
WIND_LOADS_KN_PER_M2: dict[str, float] = {
    "coastal_basic": 1.5,
    "plains_basic": 0.8,
    "hills_basic": 1.2,
}

SEISMIC_ZONES: dict[str, dict] = {
    "zone_II": {"z_factor": 0.10, "examples": "most of South India peninsula"},
    "zone_III": {"z_factor": 0.16, "examples": "Mumbai, Kolkata, Chennai"},
    "zone_IV": {"z_factor": 0.24, "examples": "Delhi NCR"},
    "zone_V": {"z_factor": 0.36, "examples": "NE India, Kutch, Himalayas"},
}

# Column spacing — BRD: 5-8m optimal.
COLUMN_SPACING_M: dict[str, tuple[float, float]] = {
    "optimal_rcc": (5.0, 8.0),
    "optimal_steel": (6.0, 12.0),
    "residential": (3.5, 6.0),
    "commercial_office": (7.5, 9.0),
    "industrial": (9.0, 15.0),
    "parking_aligned_bays": (7.5, 8.0),
}

# Span limits by material (simply supported beam, typical residential/commercial).
SPAN_LIMITS_M: dict[str, tuple[float, float]] = {
    "timber_beam": (3.0, 6.0),
    "engineered_wood_glulam": (6.0, 12.0),
    "steel_i_beam": (6.0, 18.0),
    "rcc_beam": (4.0, 10.0),
    "rcc_prestressed": (10.0, 25.0),
    "rcc_flat_slab": (6.0, 9.0),
    "one_way_slab": (3.0, 4.5),
    "two_way_slab": (4.0, 7.0),
}

# Foundation guidance by soil bearing capacity (kN/m^2).
FOUNDATION_BY_SOIL: dict[str, dict] = {
    "soft_clay": {"sbc_kn_m2": 50, "type": "raft or pile"},
    "firm_clay": {"sbc_kn_m2": 100, "type": "isolated or strip footing"},
    "dense_sand": {"sbc_kn_m2": 200, "type": "isolated footing"},
    "hard_gravel": {"sbc_kn_m2": 450, "type": "isolated footing"},
    "soft_rock": {"sbc_kn_m2": 900, "type": "spread footing"},
    "hard_rock": {"sbc_kn_m2": 3300, "type": "direct bearing"},
}

MATERIAL_STRENGTHS_MPA: dict[str, dict] = {
    "concrete_M20": {"fck": 20, "typical_use": "residential slab/beam"},
    "concrete_M25": {"fck": 25, "typical_use": "multi-storey residential"},
    "concrete_M30": {"fck": 30, "typical_use": "commercial / seismic zones"},
    "steel_Fe415": {"fy": 415, "typical_use": "general RCC reinforcement"},
    "steel_Fe500": {"fy": 500, "typical_use": "modern RCC, high-rise"},
    "structural_steel_E250": {"fy": 250, "typical_use": "hot-rolled sections"},
    "structural_steel_E350": {"fy": 350, "typical_use": "high-performance"},
}


def check_span(material: str, span_m: float) -> dict:
    spec = SPAN_LIMITS_M.get(material)
    if not spec:
        return {"status": "unknown", "message": f"No span data for {material}."}
    lo, hi = spec
    if span_m > hi:
        return {"status": "warn_high", "message": f"Span {span_m}m exceeds {material} max {hi}m. Consider alternative."}
    if span_m < lo:
        return {"status": "ok", "message": f"Well within {material} range."}
    return {"status": "ok", "message": f"Within {material} typical range {lo}-{hi}m."}
