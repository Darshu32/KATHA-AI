"""Material specification sheet builder (BRD Layer 3B)."""

from __future__ import annotations

from app.knowledge import materials as materials_kb


def build(graph: dict) -> dict:
    """Return a structured material spec:
    {
        "primary_structure": [ ... ],
        "secondary_materials": [ ... ],
        "hardware": [ ... ],
        "upholstery": [ ... ],
        "finishing": [ ... ],
        "total_notes": {...},
    }
    Each item dict has: name, grade, finish, color, supplier, lead_time_weeks, cost_inr_per_unit, unit.
    """
    primary: list[dict] = []
    secondary: list[dict] = []
    hardware: list[dict] = []
    upholstery: list[dict] = []
    finishing: list[dict] = []

    seen: set[str] = set()
    for mat in graph.get("materials", []):
        key = (mat.get("name") or "").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        row = _build_row(mat)
        bucket = _classify(mat, key)
        {
            "primary": primary,
            "secondary": secondary,
            "hardware": hardware,
            "upholstery": upholstery,
            "finishing": finishing,
        }[bucket].append(row)

    return {
        "primary_structure": primary,
        "secondary_materials": secondary,
        "hardware": hardware,
        "upholstery": upholstery,
        "finishing": finishing,
        "total_notes": {
            "waste_factor_pct": 12,
            "adjusted_note": "Apply 10-15% waste factor to quantities; finish cost typically adds 15-25% of material cost.",
        },
    }


def _classify(mat: dict, key: str) -> str:
    cat = (mat.get("category") or "").lower()
    if cat in {"fabric", "leather"} or any(k in key for k in ("leather", "linen", "cotton", "wool", "velvet", "bouclé", "boucle")):
        return "upholstery"
    if any(k in key for k in ("knob", "handle", "hinge", "lock", "bracket", "fastener")):
        return "hardware"
    if any(k in key for k in ("lacquer", "paint", "varnish", "stain", "wax", "powder", "anodise", "anodize")):
        return "finishing"
    if cat == "wood" or any(k in key for k in ("walnut", "oak", "teak", "plywood", "mdf", "rubberwood")):
        return "primary"
    if cat == "metal" or any(k in key for k in ("steel", "aluminium", "aluminum", "brass", "iron")):
        return "secondary"
    return "secondary"


def _build_row(mat: dict) -> dict:
    name = mat.get("name") or "Unnamed"
    norm = name.lower().replace(" ", "_")
    wood = materials_kb.wood_summary(norm) or materials_kb.wood_summary(norm.split("_")[0])
    metal = materials_kb.METALS.get(norm)

    if wood:
        return {
            "name": name,
            "grade": "Seasoned grade A",
            "finish": "Natural oil (default)",
            "color": mat.get("color") or "—",
            "supplier": "Local certified mill",
            "lead_time_weeks": wood.get("lead_time_weeks"),
            "cost_inr": wood.get("cost_inr_kg"),
            "unit": "kg",
            "properties": {
                "density_kg_m3": wood.get("density_kg_m3"),
                "mor_mpa": wood.get("mor_mpa"),
                "moe_mpa": wood.get("moe_mpa"),
            },
        }
    if metal:
        return {
            "name": name,
            "grade": norm.upper(),
            "finish": "Powder coat (default)",
            "color": mat.get("color") or "—",
            "supplier": "Local fabricator",
            "lead_time_weeks": (6, 10),
            "cost_inr": metal.get("cost_inr_kg"),
            "unit": "kg",
            "properties": {
                "density_kg_m3": metal.get("density_kg_m3"),
                "yield_mpa": metal.get("yield_mpa"),
            },
        }
    return {
        "name": name,
        "grade": "—",
        "finish": "—",
        "color": mat.get("color") or "—",
        "supplier": "TBD",
        "lead_time_weeks": None,
        "cost_inr": None,
        "unit": "m²",
        "properties": {},
    }
