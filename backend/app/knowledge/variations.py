"""Design variation rules (BRD 1C — Design Variations).

Defines the four canonical variation axes the platform supports:

  1. Parametric variations — dimension ranges, material swaps within a family
  2. Style adaptations    — moving a design from one theme to another
  3. Modular extensions   — how pieces combine (sofa modules, shelving units…)
  4. Customization        — colour, finish, hardware knobs

Values here are *rules*, not specific outcomes — the LLM stage reads
these alongside the brief and theme rules to produce concrete variants.
Helpers stay pure (no LLM calls, no DB) so they compose into the
generation pipeline without side effects.
"""

from __future__ import annotations

from typing import Iterable

from app.knowledge import ergonomics, materials, themes


# ── 1. Parametric variations ────────────────────────────────────────────────
# Per-axis flex an item's nominal dimension can take while staying
# within ergonomic and structural limits. Stored as ± percent.
# These are *additional* to the ergonomic ranges in ergonomics.py — the
# helper below returns the intersection so you never get a value that
# breaks both at once.
PARAMETRIC_DIMENSION_FLEX_PCT: dict[str, dict[str, float]] = {
    "chair": {
        "seat_height_mm": 8.0,        # tolerable comfort drift
        "seat_depth_mm": 8.0,
        "overall_width_mm": 12.0,
        "overall_depth_mm": 12.0,
    },
    "table": {
        "height_mm": 4.0,             # ergonomic — narrow band
        "length_mm": 20.0,
        "width_mm": 20.0,
        "depth_mm": 20.0,
    },
    "bed": {
        "platform_height_mm": 8.0,
        "raised_height_mm": 8.0,
    },
    "storage": {
        "depth_mm": 15.0,
        "height_mm": 15.0,
        "shelf_pitch_mm": 20.0,
    },
}


def parametric_dimension_range(
    *,
    category: str,
    item: str,
    dim: str,
) -> dict | None:
    """Intersect ergonomic range × parametric flex band for an item dimension.

    Returns None if the item or dim isn't known to the ergonomics tables.
    """
    table = {"chair": ergonomics.CHAIRS, "table": ergonomics.TABLES,
             "bed": ergonomics.BEDS, "storage": ergonomics.STORAGE}.get(category.lower())
    if not table or item not in table:
        return None
    spec = table[item]
    if dim not in spec:
        return None
    raw = spec[dim]
    if not isinstance(raw, tuple) or len(raw) != 2:
        return None
    ergo_lo, ergo_hi = raw

    flex_pct = PARAMETRIC_DIMENSION_FLEX_PCT.get(category.lower(), {}).get(dim)
    if flex_pct is None:
        return {
            "category": category, "item": item, "dim": dim,
            "ergonomic_range": raw, "flex_pct": None,
            "variation_range": raw,
        }
    nominal = (ergo_lo + ergo_hi) / 2.0
    flex = nominal * flex_pct / 100.0
    var_lo = max(ergo_lo, nominal - flex)
    var_hi = min(ergo_hi, nominal + flex)
    return {
        "category": category, "item": item, "dim": dim,
        "ergonomic_range": raw,
        "flex_pct": flex_pct,
        "variation_range": (round(var_lo, 1), round(var_hi, 1)),
    }


# Material-swap rules — which materials substitute for which inside a family
# without breaking the BRD envelope (density / strength / cost / lead time).
MATERIAL_SWAP_FAMILIES: dict[str, list[str]] = {
    "solid_wood_warm": ["walnut", "teak", "rubberwood"],
    "solid_wood_light": ["oak", "rubberwood"],
    "panel_substrate": ["plywood_marine", "mdf"],
    "structural_metal": ["mild_steel", "stainless_steel_304"],
    "accent_metal": ["brass", "stainless_steel_304", "aluminium_6061"],
    "premium_upholstery": ["leather_genuine_grade_A", "leather_genuine_grade_B", "fabric_wool_blend"],
    "everyday_upholstery": ["fabric_cotton", "fabric_linen", "fabric_synthetic_blend"],
    "performance_upholstery": ["fabric_performance_poly", "fabric_synthetic_blend"],
    "seat_foam": ["HD36", "HR40"],
}


def compatible_materials(material: str) -> list[str]:
    """Return other materials in the same BRD swap family (excluding the input)."""
    key = material.strip().lower().replace(" ", "_").replace("-", "_")
    matches: list[str] = []
    for family in MATERIAL_SWAP_FAMILIES.values():
        if key in family:
            matches.extend(m for m in family if m != key)
    # dedupe while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for m in matches:
        if m not in seen:
            out.append(m)
            seen.add(m)
    return out


# ── 2. Style adaptations ────────────────────────────────────────────────────
# How a design's theme can shift. Pulls live from knowledge.themes so we
# never desync. Adaptation pairs flag where the move is "natural" vs
# "requires re-think" (e.g. mid-century → industrial keeps lines but
# changes palette; mid-century → traditional is a heavier pivot).
STYLE_ADAPTATION_AFFINITY: dict[tuple[str, str], str] = {
    ("pedestal", "contemporary"):           "natural",
    ("pedestal", "modern"):                 "natural",
    ("pedestal", "mid_century_modern"):     "moderate",
    ("contemporary", "modern"):             "natural",
    ("contemporary", "mid_century_modern"): "moderate",
    ("modern", "mid_century_modern"):       "moderate",
    ("mid_century_modern", "contemporary"): "moderate",
    ("custom", "*"):                        "open",
}


def style_adaptation_plan(*, from_theme: str, to_theme: str) -> dict:
    """Describe what changes when migrating a piece between themes.

    Returns the source + target rule packs (palette, hardware, signature
    moves) plus an affinity tag the LLM uses to size the rewrite.
    """
    src = themes.get(from_theme)
    dst = themes.get(to_theme)
    if src is None or dst is None:
        return {
            "from": from_theme,
            "to": to_theme,
            "available": False,
            "note": "Source or target theme has no parametric rule pack; treat as 'custom'.",
        }
    affinity = (
        STYLE_ADAPTATION_AFFINITY.get((from_theme, to_theme))
        or STYLE_ADAPTATION_AFFINITY.get(("custom", "*"))
        if from_theme == "custom"
        else STYLE_ADAPTATION_AFFINITY.get((from_theme, to_theme), "moderate")
    )
    return {
        "from": from_theme,
        "to": to_theme,
        "available": True,
        "affinity": affinity,
        "swap": {
            "primary_materials":  {"from": src["material_palette"].get("primary", []),
                                   "to": dst["material_palette"].get("primary", [])},
            "colour_palette":     {"from": src.get("colour_palette", []),
                                   "to": dst.get("colour_palette", [])},
            "hardware":           {"from": src.get("hardware", {}),
                                   "to": dst.get("hardware", {})},
            "signature_moves":    {"drop": src.get("signature_moves", []),
                                   "introduce": dst.get("signature_moves", [])},
        },
    }


# ── 3. Modular extensions ───────────────────────────────────────────────────
# Module families: a piece can extend along one or two axes by snapping
# additional units of the same kind. Constraints below keep the assembly
# proportionate (won't allow infinite chaining).
MODULAR_FAMILIES: dict[str, dict] = {
    "sofa_modular": {
        "module_width_mm": 800,
        "axis": "linear",
        "min_modules": 2,
        "max_modules": 6,
        "joinery": "corner block + bolt-on bracket",
        "configurations": ["I", "L", "U"],
    },
    "shelving_modular": {
        "module_width_mm": 600,
        "axis": "linear+vertical",
        "min_modules": 1,
        "max_modules": 8,
        "joinery": "side-bolt + back-stiffener",
        "configurations": ["wall-run", "L-corner", "freestanding-bay"],
    },
    "kitchen_base_modular": {
        "module_width_mm": 600,
        "axis": "linear",
        "min_modules": 2,
        "max_modules": 12,
        "joinery": "carcass-to-carcass screw + shared plinth",
        "configurations": ["I", "L", "U", "island"],
    },
    "wardrobe_modular": {
        "module_width_mm": 900,
        "axis": "linear",
        "min_modules": 1,
        "max_modules": 5,
        "joinery": "side-bolt + top-rail",
        "configurations": ["wall-run", "L-walk-in", "U-walk-in"],
    },
}


def modular_options(family: str) -> dict | None:
    spec = MODULAR_FAMILIES.get(family)
    if spec is None:
        return None
    spans = [
        {
            "modules": n,
            "linear_width_mm": n * spec["module_width_mm"],
        }
        for n in range(spec["min_modules"], spec["max_modules"] + 1)
    ]
    return {**spec, "available_spans": spans}


# ── 4. Customization options ────────────────────────────────────────────────
# Knobs the client can tweak post-design without re-engineering. Cost
# impact is expressed as a percent uplift so the estimator can apply it
# to a base unit cost dynamically.
CUSTOMIZATION_OPTIONS: dict[str, dict] = {
    "color": {
        "options": ["palette_default", "palette_extended", "RAL_match", "Pantone_match"],
        "cost_uplift_pct": {
            "palette_default": (0, 0),
            "palette_extended": (3, 6),
            "RAL_match": (5, 10),
            "Pantone_match": (8, 15),
        },
    },
    "finish": {
        # Pull from materials.FINISHES so the catalogue stays in one place.
        "options": list(materials.FINISHES.keys()),
        "cost_uplift_pct": {
            "lacquer_pu": (0, 5),
            "melamine": (-5, 0),
            "wax_oil": (5, 10),
            "powder_coat": (0, 5),
            "anodise": (5, 12),
        },
    },
    "hardware": {
        "options": ["concealed", "exposed_brass", "exposed_steel", "leather_pull", "designer_pull"],
        "cost_uplift_pct": {
            "concealed": (0, 3),
            "exposed_brass": (8, 18),
            "exposed_steel": (3, 8),
            "leather_pull": (10, 20),
            "designer_pull": (15, 35),
        },
    },
}


def customization_palette(family: str) -> dict | None:
    """Return the customization knob for a single axis (color / finish / hardware)."""
    return CUSTOMIZATION_OPTIONS.get(family.lower())


def customization_summary() -> dict:
    """Compact rollup of every customization knob — for LLM grounding."""
    return {
        family: {
            "options": spec["options"],
            "uplift_pct_band": spec["cost_uplift_pct"],
        }
        for family, spec in CUSTOMIZATION_OPTIONS.items()
    }


# ── BRD rollup constant the LLM cites ───────────────────────────────────────
DESIGN_VARIATIONS_BRD_SPEC: dict = {
    "parametric": {
        "dimension_flex_pct_by_category": PARAMETRIC_DIMENSION_FLEX_PCT,
        "material_swap_families": MATERIAL_SWAP_FAMILIES,
    },
    "style_adaptations": {
        "affinity_matrix": {f"{a}->{b}": v for (a, b), v in STYLE_ADAPTATION_AFFINITY.items()},
    },
    "modular": {family: spec for family, spec in MODULAR_FAMILIES.items()},
    "customization": list(CUSTOMIZATION_OPTIONS.keys()),
}


def variations_for_item(*, category: str, item: str, materials_in_use: Iterable[str] = ()) -> dict:
    """Aggregate variation envelope for a single item.

    Surfaces all four BRD axes for the LLM in one structured payload:
      • dimension flex per dim
      • material swap candidates
      • applicable modular family (if any)
      • full customization palette
    """
    table = {"chair": ergonomics.CHAIRS, "table": ergonomics.TABLES,
             "bed": ergonomics.BEDS, "storage": ergonomics.STORAGE}.get(category.lower())
    dim_ranges: dict[str, dict] = {}
    if table and item in table:
        for dim, val in table[item].items():
            if isinstance(val, tuple) and len(val) == 2:
                vr = parametric_dimension_range(category=category, item=item, dim=dim)
                if vr:
                    dim_ranges[dim] = vr

    swaps: dict[str, list[str]] = {
        m: compatible_materials(m) for m in materials_in_use if m
    }

    modular_family = None
    if "sofa" in item:
        modular_family = "sofa_modular"
    elif item in {"bookshelf", "object_shelf", "display_shelf"}:
        modular_family = "shelving_modular"
    elif item in {"kitchen_cabinet_base", "kitchen_cabinet_wall", "counter"}:
        modular_family = "kitchen_base_modular"
    elif item == "wardrobe":
        modular_family = "wardrobe_modular"

    return {
        "category": category,
        "item": item,
        "parametric_dimension_ranges": dim_ranges,
        "material_swap_candidates": swaps,
        "modular_family": modular_options(modular_family) if modular_family else None,
        "customization": customization_summary(),
    }
