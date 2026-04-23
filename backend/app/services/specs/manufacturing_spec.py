"""Manufacturing specification builder (BRD Layer 3C).

Turns the graph into per-trade notes (woodworking, metal, upholstery,
assembly) with tolerances, joinery, and lead times pulled from the
manufacturing knowledge module.
"""

from __future__ import annotations

from app.knowledge import manufacturing as mfg

_WOOD_KEYS = ("walnut", "oak", "teak", "plywood", "mdf", "rubberwood", "wood")
_METAL_KEYS = ("steel", "aluminium", "aluminum", "brass", "iron")
_UPHOLSTERED_TYPES = {"sofa", "lounge_chair", "chair", "dining_chair", "office_chair", "bed", "armchair"}


def build(graph: dict) -> dict:
    wood_items: list[str] = []
    metal_items: list[str] = []
    upholstered_items: list[str] = []
    assembly_items: list[str] = []

    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "").lower()
        mat = (obj.get("material") or "").lower()
        if any(k in mat for k in _WOOD_KEYS):
            wood_items.append(otype)
        if any(k in mat for k in _METAL_KEYS):
            metal_items.append(otype)
        if otype in _UPHOLSTERED_TYPES:
            upholstered_items.append(otype)
        assembly_items.append(otype)

    return {
        "woodworking": {
            "applies_to": sorted(set(wood_items)) or ["—"],
            "tolerance_structural_mm": mfg.tolerance_for("woodworking_precision"),
            "tolerance_cosmetic_mm": mfg.tolerance_for("woodworking_standard"),
            "joinery_recommended": [
                {"method": "mortise_tenon", **mfg.JOINERY["mortise_tenon"]},
                {"method": "dowel", **mfg.JOINERY["dowel"]},
                {"method": "pocket_hole", **mfg.JOINERY["pocket_hole"]},
            ],
            "finishing_sequence": ["Sand P120 → P220", "Stain (optional)", "Primer", "Top coat (2–3 coats)"],
            "lead_time_weeks": mfg.lead_time_for("woodworking_furniture"),
            "moq_pieces": mfg.MOQ["woodworking_small_batch"],
        },
        "metal_fabrication": {
            "applies_to": sorted(set(metal_items)) or ["—"],
            "welding_preferred": [
                {"method": "GMAW_MIG", **mfg.WELDING["GMAW_MIG"]},
                {"method": "GTAW_TIG", **mfg.WELDING["GTAW_TIG"]},
            ],
            "bending_rule": mfg.BENDING_RULE,
            "tolerance_structural_mm": mfg.tolerance_for("metal_structural"),
            "tolerance_cosmetic_mm": mfg.tolerance_for("metal_cosmetic"),
            "powder_coat": {"thickness_microns": (60, 100), "cure_temp_c": 200, "cure_time_min": (10, 15)},
            "lead_time_weeks": mfg.lead_time_for("metal_fabrication"),
        },
        "upholstery": {
            "applies_to": sorted(set(upholstered_items)) or ["—"],
            "webbing_tension_kg_per_inch": mfg.UPHOLSTERY_SPEC["webbing_tension_kg_per_inch"],
            "stitch_density_per_inch": mfg.UPHOLSTERY_SPEC["stitch_density_per_inch"],
            "foam_tolerance_mm": mfg.UPHOLSTERY_SPEC["foam_tolerance_mm"],
            "zipper_placement": "Concealed at rear base; YKK #5 minimum.",
            "lead_time_weeks": mfg.lead_time_for("upholstery_post_frame"),
        },
        "assembly": {
            "sequence": [
                "Frame + joinery dry-fit",
                "Sand + finish while separable",
                "Hardware install (torque per spec)",
                "Upholstery mount",
                "Final QC + packaging",
            ],
            "qa_gates": mfg.QA_GATES,
            "packaging": "Edge-protected corrugate; corner foam; woven strap.",
        },
    }
