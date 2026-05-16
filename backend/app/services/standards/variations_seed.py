"""Stage 3F — design-variations seed builder.

Translates :mod:`app.knowledge.variations` literals into
``building_standards`` rows tagged ``category='design'`` so BRD §1C
Design Variations is sourced from versioned DB rows instead of frozen
Python dicts.

Slug naming
-----------
  - ``design_variation_parametric_<category>`` — per-category flex
    bands (chair / table / bed / storage).
  - ``design_variation_swap_<family>`` — material substitution family
    (solid_wood_warm, structural_metal, …).
  - ``design_variation_style_affinity`` — single row holding the
    theme-to-theme affinity matrix.
  - ``design_variation_modular_<family>`` — per-modular family spec
    (sofa_modular, shelving_modular, kitchen_base_modular,
    wardrobe_modular).
  - ``design_variation_customization_<axis>`` — per-axis customization
    palette (color / finish / hardware) with cost-uplift bands.

Subcategories carry the BRD axis name so a single SQL filter can pull
"all parametric variations" or "all modular families" cleanly.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import variations as variations_kb


def _new_id() -> str:
    return uuid4().hex


def _serialise(value: Any) -> Any:
    """Coerce tuples → lists for JSON-friendly storage."""
    if isinstance(value, tuple):
        return [_serialise(v) for v in value]
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialise(v) for k, v in value.items()}
    return value


def _row(
    slug: str,
    *,
    display_name: str,
    data: dict[str, Any],
    subcategory: str,
    notes: str | None = None,
    source_section: str = "BRD §1C — Design Variations",
    source_tag: str = "seed:design_variations",
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "slug": slug,
        "category": "design",
        "jurisdiction": "india_nbc",
        "subcategory": subcategory,
        "display_name": display_name,
        "notes": notes,
        "data": _serialise(data),
        "source_section": source_section,
        "source_doc": "BRD-Phase-1",
        "source": source_tag,
    }


# ─────────────────────────────────────────────────────────────────────
# 1. Parametric — dimension flex per category
# ─────────────────────────────────────────────────────────────────────


def _parametric_flex_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"design_variation_parametric_{category}",
            subcategory="variation_parametric",
            display_name=f"Parametric flex — {category}",
            data={
                "category": category,
                "dimension_flex_pct": dict(per_dim),
            },
            notes=(
                f"BRD §1C parametric variation envelope for {category} "
                "dimensions. Percentages are tolerable drift around the "
                "ergonomic midpoint — intersected with ergonomics ranges "
                "at lookup time so a value never breaks both bounds."
            ),
        )
        for category, per_dim in variations_kb.PARAMETRIC_DIMENSION_FLEX_PCT.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# 2. Parametric — material swap families
# ─────────────────────────────────────────────────────────────────────


def _material_swap_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"design_variation_swap_{family}",
            subcategory="variation_swap",
            display_name=f"Material swap family — {family.replace('_', ' ')}",
            data={
                "family": family,
                "members": list(members),
            },
            notes=(
                "Materials in this family substitute for each other without "
                "breaking the BRD envelope (density / strength / cost / "
                "lead-time)."
            ),
        )
        for family, members in variations_kb.MATERIAL_SWAP_FAMILIES.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# 3. Style adaptations — theme-to-theme affinity
# ─────────────────────────────────────────────────────────────────────


def _style_affinity_row() -> dict[str, Any]:
    pairs = {
        f"{a}->{b}": tag
        for (a, b), tag in variations_kb.STYLE_ADAPTATION_AFFINITY.items()
    }
    return _row(
        "design_variation_style_affinity",
        subcategory="variation_style",
        display_name="Style adaptation affinity matrix",
        data={"affinity_matrix": pairs},
        notes=(
            "BRD §1C theme-to-theme adaptation tags. 'natural' = same "
            "language, drop-in swap. 'moderate' = palette + signature "
            "moves shift, lines roughly hold. 'open' = source theme is "
            "custom; treat target as the anchor."
        ),
    )


# ─────────────────────────────────────────────────────────────────────
# 4. Modular extensions
# ─────────────────────────────────────────────────────────────────────


def _modular_family_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"design_variation_modular_{family}",
            subcategory="variation_modular",
            display_name=f"Modular family — {family.replace('_', ' ')}",
            data={"family": family, **dict(spec)},
            notes=(
                "Per BRD §1C — modular axis + module-width band keeps "
                "the assembly proportionate. Configurations list the "
                "stable layouts the LLM may pick from."
            ),
        )
        for family, spec in variations_kb.MODULAR_FAMILIES.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# 5. Customization options
# ─────────────────────────────────────────────────────────────────────


def _customization_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"design_variation_customization_{axis}",
            subcategory="variation_customization",
            display_name=f"Customization palette — {axis}",
            data={
                "axis": axis,
                "options": list(spec["options"]),
                "cost_uplift_pct": dict(spec["cost_uplift_pct"]),
            },
            notes=(
                "BRD §1C customization axis. Cost uplifts are percent "
                "bands applied to base unit cost — the estimator picks a "
                "value inside the band per option chosen."
            ),
        )
        for axis, spec in variations_kb.CUSTOMIZATION_OPTIONS.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# Public builder — used by the alembic migration
# ─────────────────────────────────────────────────────────────────────


def build_design_variations_seed_rows() -> list[dict[str, Any]]:
    return [
        *_parametric_flex_rows(),
        *_material_swap_rows(),
        _style_affinity_row(),
        *_modular_family_rows(),
        *_customization_rows(),
    ]
