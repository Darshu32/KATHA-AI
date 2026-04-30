"""Material physical properties, cost, lead-time data.

⚠️ STAGE 1 PARTIAL DEPRECATION NOTICE — April 2026
---------------------------------------------------
**Cost-related fields** (``cost_inr_kg``, ``cost_inr_m2``, ``cost_inr_m3``,
``lead_time_weeks``) have been migrated to the ``material_prices`` DB
table. The cost engine reads them via
``app.repositories.pricing.MaterialPriceRepository`` and accepts admin
updates through the Stage 1 pricing endpoints.

**Physical properties** (density, MOR, MOE, finish_options, durability,
colourfastness) remain authoritative HERE — they're not market-volatile.
Stage 3 migrates the remaining cost-related consumers; physical-property
consumers stay on this module.

DO NOT update cost fields directly — go through the admin pricing
endpoints so changes are versioned + audited.

---

Per BRD Layer 1C. Units noted per field. INR for costs (India context).
"""

from __future__ import annotations

# ── Wood ─────────────────────────────────────────────────────────────────────
# density kg/m^3, MOR (modulus of rupture) MPa, MOE MPa, cost INR/kg (rough),
# lead_time_weeks (seasoned stock).
#
# BRD 1C — Wood envelope for the primary solid-wood palette
# (Walnut, Oak, Teak, Plywood):
#   density 600–900 kg/m³, MOR 50–100 MPa, MOE 8 000–15 000 MPa,
#   cost ₹300–800/kg base, lead time 2–4 weeks (seasoning done).
#   Canonical finish palette: natural, stain, lacquer, veneer.
WOOD_BRD_RANGES: dict[str, tuple[float, float]] = {
    "density_kg_m3": (600, 900),
    "mor_mpa": (50, 100),
    "moe_mpa": (8000, 15000),
    "cost_inr_kg": (300, 800),
    "lead_time_weeks": (2, 4),
}
WOOD_BRD_FINISH_PALETTE: tuple[str, ...] = ("natural", "stain", "lacquer", "veneer")

WOOD: dict[str, dict] = {
    "walnut": {
        "density_kg_m3": 640,
        "mor_mpa": 100,
        "moe_mpa": 11600,
        "cost_inr_kg": (500, 800),
        "lead_time_weeks": (2, 4),
        "finish_options": ["natural", "stain", "lacquer", "veneer", "natural oil"],
        "aesthetic": "deep brown, rich grain, mid-century favourite",
    },
    "oak": {
        "density_kg_m3": 750,
        "mor_mpa": 95,
        "moe_mpa": 12300,
        "cost_inr_kg": (350, 550),
        "lead_time_weeks": (2, 4),
        "finish_options": ["natural", "stain", "lacquer", "veneer", "fumed", "lime-wash"],
        "aesthetic": "light to medium brown, prominent grain",
    },
    "teak": {
        "density_kg_m3": 680,
        "mor_mpa": 95,
        "moe_mpa": 12000,
        "cost_inr_kg": (600, 900),        # BRD ceiling is ₹800/kg; premium teak exceeds.
        "lead_time_weeks": (2, 4),
        "finish_options": ["natural", "stain", "lacquer", "veneer", "natural oil", "polish"],
        "aesthetic": "golden brown, weather-resistant, Indian classic",
    },
    "plywood_marine": {
        "density_kg_m3": 640,
        "mor_mpa": 40,                    # below BRD 50 MPa floor — engineered, not solid.
        "moe_mpa": 7500,                  # below BRD 8 GPa floor — engineered panel.
        "cost_inr_kg": (140, 220),        # priced as sheet stock, not per-kg solid wood.
        "lead_time_weeks": (1, 2),
        "finish_options": ["natural", "stain", "lacquer", "veneer", "laminate", "paint"],
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
# BRD 1C — Metals envelope (Steel, Aluminum, Brass):
#   Steel:    ρ 7 850 kg/m³, yield 250–400 MPa
#   Aluminum: ρ 2 700 kg/m³, yield  70–200 MPa
#   Brass:    ρ 8 400 kg/m³, non-magnetic
#   Finish palette: powder coat, anodize, polished, brushed
#   Cost:   ₹150–400/kg (carbon steel + aluminium band; brass exceeds)
#   Fabrication: welding, bending, machining
METALS_BRD_SPECS: dict[str, dict] = {
    "steel": {"density_kg_m3": 7850, "yield_mpa": (250, 400)},
    "aluminum": {"density_kg_m3": 2700, "yield_mpa": (70, 200)},
    "brass": {"density_kg_m3": 8400, "non_magnetic": True},
}
METALS_BRD_COST_INR_KG: tuple[int, int] = (150, 400)
METALS_BRD_FINISH_PALETTE: tuple[str, ...] = ("powder coat", "anodize", "polished", "brushed")
METALS_BRD_FABRICATION: tuple[str, ...] = ("welding", "bending", "machining")

METALS: dict[str, dict] = {
    "mild_steel": {
        "density_kg_m3": 7850,
        "yield_mpa": (250, 400),            # BRD: 250–400 MPa (Fe250 → Fe500+ grades)
        "ultimate_mpa": 410,
        "cost_inr_kg": (60, 90),            # below BRD ₹150 floor — raw flat stock.
        "finish_options": ["powder coat", "polished", "brushed", "paint", "galvanise"],
        "fabrication": ["welding", "bending", "machining", "laser cut"],
    },
    "stainless_steel_304": {
        "density_kg_m3": 8000,
        "yield_mpa": 215,
        "ultimate_mpa": 505,
        "cost_inr_kg": (220, 320),          # within BRD ₹150–400/kg band.
        "finish_options": ["powder coat", "polished", "brushed", "mirror polish", "satin"],
        "fabrication": ["welding", "bending", "machining"],
    },
    "aluminium_6061": {
        "density_kg_m3": 2700,              # BRD: 2700 kg/m³
        "yield_mpa": (70, 200),             # BRD: 70–200 MPa across tempers
        "ultimate_mpa": 310,
        "cost_inr_kg": (250, 400),          # within BRD ₹150–400/kg band.
        "finish_options": ["anodize", "powder coat", "polished", "brushed"],
        "fabrication": ["welding", "bending", "machining", "extrude", "CNC"],
    },
    "brass": {
        "density_kg_m3": 8400,              # BRD: 8400 kg/m³
        "yield_mpa": 200,
        "ultimate_mpa": 500,
        "non_magnetic": True,               # BRD: non-magnetic
        "cost_inr_kg": (700, 950),          # above BRD ₹400 ceiling — premium alloy.
        "finish_options": ["polished", "brushed", "powder coat", "antique"],
        "fabrication": ["welding", "bending", "machining", "cast"],
        "aesthetic": "warm gold; mid-century and luxury accent",
    },
}

# ── Upholstery ───────────────────────────────────────────────────────────────
# BRD 1C — Upholstery envelope:
#   Leather: grades A–D, thickness 1.2–1.5 mm, ₹800–3000/m²
#   Fabric: cotton / linen / wool / synthetic blends, ₹300–1500/m²
#   Foam:   high-density (HD36), density 180 kg/m³, ₹150–400/m³
#   Durability (Martindale rubs): 15K–100K, commercial standard ≥30K
#   Colour fastness: ≥4/5 for upholstered furniture
UPHOLSTERY_LEATHER_BRD_SPEC: dict = {
    "grades": ("A", "B", "C", "D"),
    "thickness_mm": (1.2, 1.5),
    "cost_inr_m2": (800, 3000),
}
UPHOLSTERY_FABRIC_BRD_SPEC: dict = {
    "types": ("cotton", "linen", "wool", "synthetic_blend"),
    "cost_inr_m2": (300, 1500),
}
FOAM_BRD_SPEC: dict = {
    "grade": "HD36",
    "density_kg_m3": 180,          # BRD value — flag: commercial HD36 is ~36 kg/m³.
    "cost_inr_m3": (150, 400),     # BRD value — flag: commercial foam is ~₹10k–20k/m³.
    "note": (
        "BRD spec recorded verbatim. Commercial HD36 polyurethane foam is "
        "typically ~36 kg/m³ at ₹10,000–20,000 per m³; values diverge from "
        "BRD — re-verify source before citing to client."
    ),
}
UPHOLSTERY_DURABILITY_BRD: dict = {
    "rubs_range_k": (15, 100),
    "commercial_min_k": 30,
}
UPHOLSTERY_COLOURFASTNESS_MIN: int = 4   # /5 — BRD floor for upholstered pieces.

UPHOLSTERY: dict[str, dict] = {
    "leather_genuine_grade_A": {
        "thickness_mm": (1.3, 1.5),      # BRD band: 1.2–1.5 mm
        "cost_inr_m2": (2000, 3000),     # top of BRD band: premium full-grain
        "durability_rubs_k": (50, 100),
        "colourfastness": 5,
    },
    "leather_genuine_grade_B": {
        "thickness_mm": (1.2, 1.4),
        "cost_inr_m2": (1400, 2000),
        "durability_rubs_k": (30, 60),
        "colourfastness": 4,
    },
    "leather_genuine_grade_C": {
        "thickness_mm": (1.2, 1.3),
        "cost_inr_m2": (1000, 1400),
        "durability_rubs_k": (20, 40),
        "colourfastness": 4,
    },
    "leather_genuine_grade_D": {
        "thickness_mm": (1.2, 1.3),
        "cost_inr_m2": (800, 1000),      # bottom of BRD band: corrected / split leather
        "durability_rubs_k": (15, 30),
        "colourfastness": 4,
    },
    "fabric_cotton": {
        "cost_inr_m2": (300, 700),        # within BRD ₹300–1500 band
        "durability_rubs_k": (15, 30),
        "colourfastness": 4,
    },
    "fabric_linen": {
        "cost_inr_m2": (500, 1200),
        "durability_rubs_k": (20, 40),
        "colourfastness": 4,
    },
    "fabric_wool_blend": {
        "cost_inr_m2": (800, 1500),
        "durability_rubs_k": (30, 60),
        "colourfastness": 4,
    },
    "fabric_synthetic_blend": {
        "cost_inr_m2": (500, 1200),
        "durability_rubs_k": (40, 100),
        "colourfastness": 5,
        "notes": "Polyester / acrylic blends; performance-grade for heavy-use seating.",
    },
    "fabric_performance_poly": {
        "cost_inr_m2": (600, 1100),
        "durability_rubs_k": (50, 100),
        "colourfastness": 5,
    },
}

FOAM: dict[str, dict] = {
    "HD36": {
        "density_kg_m3": 36,                    # commercial reality; BRD records 180 — see FOAM_BRD_SPEC.
        "firmness": "medium-firm",
        "cost_inr_m3": (10000, 16000),          # commercial reality; BRD records ₹150–400/m³.
        "use": "sofa seat cushions",
        "brd_alignment": "HD36 grade matches BRD; density / cost deviate — flagged in FOAM_BRD_SPEC.",
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
