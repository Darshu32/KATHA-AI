"""Material physical properties, cost, lead-time data.

Per BRD Layer 1C. Units noted per field. INR for costs (India context).
"""

from __future__ import annotations

# ── Wood ─────────────────────────────────────────────────────────────────────
# density kg/m^3, MOR (modulus of rupture) MPa, MOE MPa, cost INR/kg (rough),
# lead_time_weeks (seasoned stock).
WOOD: dict[str, dict] = {
    "walnut": {
        "density_kg_m3": 640,
        "mor_mpa": 100,
        "moe_mpa": 11600,
        "cost_inr_kg": (500, 800),
        "lead_time_weeks": (2, 4),
        "finish_options": ["natural oil", "stain", "lacquer"],
        "aesthetic": "deep brown, rich grain, mid-century favourite",
    },
    "oak": {
        "density_kg_m3": 750,
        "mor_mpa": 95,
        "moe_mpa": 12300,
        "cost_inr_kg": (350, 550),
        "lead_time_weeks": (2, 4),
        "finish_options": ["natural", "fumed", "stain", "lime-wash"],
        "aesthetic": "light to medium brown, prominent grain",
    },
    "teak": {
        "density_kg_m3": 680,
        "mor_mpa": 95,
        "moe_mpa": 12000,
        "cost_inr_kg": (600, 900),
        "lead_time_weeks": (2, 4),
        "finish_options": ["natural oil", "polish"],
        "aesthetic": "golden brown, weather-resistant, Indian classic",
    },
    "plywood_marine": {
        "density_kg_m3": 640,
        "mor_mpa": 40,
        "moe_mpa": 7500,
        "cost_inr_kg": (140, 220),   # roughly derived from sheet pricing
        "lead_time_weeks": (1, 2),
        "finish_options": ["veneer", "laminate", "paint"],
        "aesthetic": "utility; typically clad",
    },
    "mdf": {
        "density_kg_m3": 750,
        "mor_mpa": 28,
        "moe_mpa": 3200,
        "cost_inr_kg": (80, 140),
        "lead_time_weeks": (1, 2),
        "finish_options": ["laminate", "veneer", "paint", "PU"],
        "aesthetic": "utility substrate",
    },
    "rubberwood": {
        "density_kg_m3": 620,
        "mor_mpa": 66,
        "moe_mpa": 9700,
        "cost_inr_kg": (200, 350),
        "lead_time_weeks": (2, 3),
        "finish_options": ["stain", "lacquer"],
        "aesthetic": "pale, uniform, budget solid-wood look",
    },
}

# ── Metals ───────────────────────────────────────────────────────────────────
METALS: dict[str, dict] = {
    "mild_steel": {
        "density_kg_m3": 7850,
        "yield_mpa": 250,
        "ultimate_mpa": 410,
        "cost_inr_kg": (60, 90),
        "finish_options": ["powder coat", "paint", "galvanise"],
        "fabrication": ["welding (GMAW/GTAW)", "bending", "laser cut"],
    },
    "stainless_steel_304": {
        "density_kg_m3": 8000,
        "yield_mpa": 215,
        "ultimate_mpa": 505,
        "cost_inr_kg": (220, 320),
        "finish_options": ["brushed", "mirror polish", "satin"],
        "fabrication": ["TIG weld", "laser cut", "press brake"],
    },
    "aluminium_6061": {
        "density_kg_m3": 2700,
        "yield_mpa": 200,
        "ultimate_mpa": 310,
        "cost_inr_kg": (250, 400),
        "finish_options": ["anodise", "powder coat"],
        "fabrication": ["extrude", "weld", "CNC"],
    },
    "brass": {
        "density_kg_m3": 8400,
        "yield_mpa": 200,
        "ultimate_mpa": 500,
        "cost_inr_kg": (700, 950),
        "finish_options": ["polished", "brushed", "antique"],
        "fabrication": ["cast", "machine"],
        "aesthetic": "warm gold; mid-century and luxury accent",
    },
}

# ── Upholstery ───────────────────────────────────────────────────────────────
UPHOLSTERY: dict[str, dict] = {
    "leather_genuine_grade_A": {
        "thickness_mm": (1.2, 1.5),
        "cost_inr_m2": (1500, 3000),
        "durability_rubs_k": (50, 100),   # Martindale rubs x1000
        "colourfastness": 4,
    },
    "leather_genuine_grade_B": {
        "thickness_mm": (1.1, 1.4),
        "cost_inr_m2": (900, 1500),
        "durability_rubs_k": (30, 60),
    },
    "fabric_cotton": {
        "cost_inr_m2": (300, 700),
        "durability_rubs_k": (15, 30),
    },
    "fabric_linen": {
        "cost_inr_m2": (500, 1200),
        "durability_rubs_k": (20, 40),
    },
    "fabric_wool_blend": {
        "cost_inr_m2": (800, 1500),
        "durability_rubs_k": (30, 60),
    },
    "fabric_performance_poly": {
        "cost_inr_m2": (600, 1100),
        "durability_rubs_k": (50, 100),
    },
}

FOAM: dict[str, dict] = {
    "HD36": {
        "density_kg_m3": 36,
        "firmness": "medium-firm",
        "cost_inr_m3": (10000, 16000),
        "use": "sofa seat cushions",
    },
    "HR40": {
        "density_kg_m3": 40,
        "firmness": "firm-resilient",
        "cost_inr_m3": (14000, 22000),
        "use": "premium seat cushions",
    },
    "memory_foam": {
        "density_kg_m3": 60,
        "firmness": "soft-contour",
        "cost_inr_m3": (20000, 35000),
        "use": "bed toppers, headrests",
    },
}

# ── Finishes & coatings ──────────────────────────────────────────────────────
FINISHES: dict[str, dict] = {
    "lacquer_pu": {
        "thickness_microns": (50, 80),
        "coats": (2, 3),
        "sheen": ["matte", "satin", "gloss"],
        "cost_inr_m2": (200, 450),
    },
    "melamine": {
        "thickness_microns": (25, 40),
        "coats": (2, 3),
        "cost_inr_m2": (120, 250),
    },
    "wax_oil": {
        "coats": (2, 3),
        "cost_inr_m2": (150, 300),
    },
    "powder_coat": {
        "thickness_microns": (60, 100),   # BRD
        "cure_temp_c": 200,
        "cure_time_min": (10, 15),
        "cost_inr_m2": (120, 220),
    },
    "anodise": {
        "thickness_microns": (15, 25),
        "cost_inr_m2": (200, 400),
    },
}


def wood_summary(species: str) -> dict | None:
    return WOOD.get(species.lower().replace(" ", "_"))
