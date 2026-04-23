"""Climate-zone design rules (BRD Phase 1 / Layer 1A).

Climatic zones follow SP 41 / NBC India Part 11 classification, extended
with practical design levers: solar orientation, glazing strategy, HVAC
load basis, passive design priorities.

Values are ranges or recommendations — they feed both the LLM prompt
(grounding) and the validator (post-generation checks).
"""

from __future__ import annotations

# ── Zone library ─────────────────────────────────────────────────────────────
# Keyed by canonical zone name used by ClimaticZoneEnum.
ZONES: dict[str, dict] = {
    "hot_dry": {
        "display_name": "Hot & Dry",
        "typical_regions": ["Rajasthan", "Gujarat (inland)", "parts of MP, TS, AP"],
        "design_temp_c": {"summer_max": 45, "winter_min": 5},
        "humidity_percent": (20, 40),
        "preferred_orientation": {
            "long_axis": "E-W",
            "primary_openings": "N, S (shaded)",
            "minimise_openings": "E, W",
        },
        "glazing": {
            "window_wall_ratio_max": 0.20,
            "shading_devices": ["deep chajjas", "jaalis", "external louvres"],
            "glazing_type": "double low-e, tinted",
        },
        "wall_strategy": {
            "u_value_target_w_m2k": 0.35,
            "techniques": ["thick masonry", "cavity wall", "external insulation"],
            "colour": "light reflective finish (SRI > 70)",
        },
        "roof_strategy": {
            "u_value_target_w_m2k": 0.28,
            "techniques": ["high-albedo coating", "insulation", "vented attic"],
        },
        "hvac": {
            "cooling_load_w_m2": (80, 130),
            "approach": "evaporative cooling viable; large sensible loads",
            "ventilation_strategy": "night flush, courtyard stack",
        },
        "passive_priorities": [
            "shade before insulate",
            "courtyards and buffer zones",
            "thermal mass on interior face",
        ],
    },
    "warm_humid": {
        "display_name": "Warm & Humid",
        "typical_regions": ["coastal India — Mumbai, Chennai, Kolkata, Goa, Kerala"],
        "design_temp_c": {"summer_max": 38, "winter_min": 18},
        "humidity_percent": (70, 95),
        "preferred_orientation": {
            "long_axis": "E-W",
            "primary_openings": "facing prevailing breeze (often SW)",
            "cross_ventilation": "mandatory",
        },
        "glazing": {
            "window_wall_ratio_max": 0.35,
            "shading_devices": ["horizontal overhangs", "verandahs", "screens"],
            "glazing_type": "single clear with deep shade; openable",
        },
        "wall_strategy": {
            "u_value_target_w_m2k": 0.55,
            "techniques": ["light envelopes", "rain-screen cladding", "ventilated cavities"],
            "finish": "mould-resistant, moisture tolerant",
        },
        "roof_strategy": {
            "u_value_target_w_m2k": 0.40,
            "techniques": ["sloped pitched roof", "over-deck insulation", "large overhangs"],
        },
        "hvac": {
            "cooling_load_w_m2": (90, 150),
            "approach": "dehumidification dominant; latent loads high",
            "ventilation_strategy": "continuous cross-ventilation; ceiling fans",
        },
        "passive_priorities": [
            "cross-ventilation",
            "rain protection and drainage",
            "mildew-resistant materials",
        ],
    },
    "composite": {
        "display_name": "Composite",
        "typical_regions": ["Delhi NCR", "UP plains", "parts of MP, Bihar"],
        "design_temp_c": {"summer_max": 45, "winter_min": 3},
        "humidity_percent": (30, 80),
        "preferred_orientation": {
            "long_axis": "E-W",
            "primary_openings": "S (winter sun), N (daylight)",
            "minimise_openings": "W",
        },
        "glazing": {
            "window_wall_ratio_max": 0.30,
            "shading_devices": ["adjustable external shading", "seasonal awnings"],
            "glazing_type": "double low-e",
        },
        "wall_strategy": {
            "u_value_target_w_m2k": 0.40,
            "techniques": ["insulated cavity wall", "light external colour"],
        },
        "roof_strategy": {
            "u_value_target_w_m2k": 0.33,
            "techniques": ["insulated flat roof", "reflective finish"],
        },
        "hvac": {
            "cooling_load_w_m2": (70, 120),
            "heating_load_w_m2": (30, 60),
            "approach": "dual-mode; heat-pump friendly",
            "ventilation_strategy": "seasonal — sealed winter, open summer/monsoon",
        },
        "passive_priorities": [
            "shade in summer, admit winter sun",
            "mixed-mode comfort",
            "insulation on roof especially",
        ],
    },
    "temperate": {
        "display_name": "Temperate",
        "typical_regions": ["Bengaluru, Pune, parts of Maharashtra Deccan"],
        "design_temp_c": {"summer_max": 34, "winter_min": 10},
        "humidity_percent": (40, 70),
        "preferred_orientation": {
            "long_axis": "E-W",
            "primary_openings": "N, S",
        },
        "glazing": {
            "window_wall_ratio_max": 0.30,
            "glazing_type": "single clear acceptable; double for premium",
        },
        "wall_strategy": {
            "u_value_target_w_m2k": 0.55,
            "techniques": ["standard insulated wall", "light finishes"],
        },
        "roof_strategy": {
            "u_value_target_w_m2k": 0.40,
        },
        "hvac": {
            "cooling_load_w_m2": (50, 90),
            "approach": "often fan-only feasible; part-load AC",
            "ventilation_strategy": "natural most of the year",
        },
        "passive_priorities": [
            "daylight and cross-ventilation",
            "comfort without full air-con",
        ],
    },
    "cold": {
        "display_name": "Cold",
        "typical_regions": ["Shimla, Manali, Srinagar, Leh, high-altitude Himalaya"],
        "design_temp_c": {"summer_max": 28, "winter_min": -15},
        "humidity_percent": (30, 60),
        "preferred_orientation": {
            "long_axis": "E-W",
            "primary_openings": "S (solar gain)",
            "minimise_openings": "N (heat loss)",
        },
        "glazing": {
            "window_wall_ratio_max": 0.25,
            "glazing_type": "double / triple low-e with argon fill",
        },
        "wall_strategy": {
            "u_value_target_w_m2k": 0.30,
            "techniques": ["thick insulation", "thermal-break framing", "air-tight envelope"],
        },
        "roof_strategy": {
            "u_value_target_w_m2k": 0.20,
            "techniques": ["pitched snow-shedding roof", "heavy insulation"],
        },
        "hvac": {
            "heating_load_w_m2": (80, 140),
            "approach": "heat-pump or hydronic; minimise infiltration",
            "ventilation_strategy": "HRV/ERV to preserve heat",
        },
        "passive_priorities": [
            "passive solar — south glazing + thermal mass",
            "super-insulated envelope",
            "airtightness",
        ],
    },
}


def get(zone: str | None) -> dict | None:
    if not zone:
        return None
    key = str(zone).strip().lower().replace("-", "_").replace(" ", "_")
    return ZONES.get(key)


def describe_for_prompt(zone: str | None) -> str:
    pack = get(zone)
    if not pack:
        return ""
    lines = [f"Climate zone: {pack['display_name']}"]
    orient = pack["preferred_orientation"]
    lines.append(
        f"- Orientation: long axis {orient.get('long_axis','')}, "
        f"openings {orient.get('primary_openings','')}, "
        f"minimise {orient.get('minimise_openings','(none)')}"
    )
    glz = pack["glazing"]
    lines.append(
        f"- Glazing: WWR <= {glz['window_wall_ratio_max']}, {glz.get('glazing_type','')}, "
        f"shading: {', '.join(glz.get('shading_devices', []))}"
    )
    lines.append(
        f"- Envelope U-targets W/m²K — wall {pack['wall_strategy']['u_value_target_w_m2k']}, "
        f"roof {pack['roof_strategy']['u_value_target_w_m2k']}"
    )
    hv = pack["hvac"]
    lines.append(f"- HVAC: {hv.get('approach','')}; ventilation — {hv.get('ventilation_strategy','')}")
    lines.append("- Passive priorities: " + "; ".join(pack["passive_priorities"]))
    return "\n".join(lines)
