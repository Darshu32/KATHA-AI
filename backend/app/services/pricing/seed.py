"""Deterministic seed-row builder for Stage 1 pricing tables.

Reads the legacy ``app.knowledge`` Python literals and emits row dicts
ready for ``bulk_insert_mappings``-style insertion. Pure functions, no
DB or network access — testable as a unit, callable from migrations.

Why this module exists
----------------------
- Keep the **migration script thin and side-effect-free**: it imports
  ``build_seed_rows()`` and calls ``op.bulk_insert``.
- Keep the **legacy constants intact** during Stage 1: other services
  still import them; we only relocate the data into the DB and let the
  cost-engine read it from there.
- Give us a **regression test surface**: we can compare the seed dict
  against the legacy module's output to detect drift.

Future
------
Stage 3 deletes the legacy modules entirely once every consumer has
migrated. At that point this seed becomes the *only* source of truth.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import costing, materials, regional_materials


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _band(value: Any) -> tuple[float, float]:
    """Coerce a BRD ``(low, high)`` band into a clean float tuple.

    Tolerates:
      - 2-tuples / 2-lists ``(low, high)``
      - scalars (returns ``(value, value)``)
      - ``None`` (raises — seed data must be specified)
    """
    if value is None:
        raise ValueError("band value missing")
    if isinstance(value, (list, tuple)):
        if len(value) == 2:
            return float(value[0]), float(value[1])
        if len(value) == 1:
            v = float(value[0])
            return v, v
        raise ValueError(f"band must have 1 or 2 elements, got {len(value)}")
    return float(value), float(value)


def _new_id() -> str:
    return uuid4().hex


# ─────────────────────────────────────────────────────────────────────
# Materials
# ─────────────────────────────────────────────────────────────────────


def _wood_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in materials.WOOD.items():
        cost_low, cost_high = _band(spec.get("cost_inr_kg"))
        lt_low, lt_high = _band(spec.get("lead_time_weeks", (2, 4)))
        rows.append(
            {
                "id": _new_id(),
                "slug": slug,
                "region": "global",
                "name": slug.replace("_", " ").title(),
                "category": "wood_solid" if slug not in {"plywood_marine", "mdf"} else "wood_panel",
                "basis_unit": "kg",
                "price_inr_low": cost_low,
                "price_inr_high": cost_high,
                "lead_time_weeks_low": lt_low,
                "lead_time_weeks_high": lt_high,
                "available_in_cities": regional_materials.MATERIAL_AVAILABILITY.get(slug),
                "extras": {
                    "density_kg_m3": spec.get("density_kg_m3"),
                    "mor_mpa": spec.get("mor_mpa"),
                    "moe_mpa": spec.get("moe_mpa"),
                    "finish_options": spec.get("finish_options", []),
                    "aesthetic": spec.get("aesthetic"),
                },
                "source": "seed:materials.WOOD",
            }
        )
    return rows


def _metal_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in materials.METALS.items():
        cost_low, cost_high = _band(spec.get("cost_inr_kg"))
        rows.append(
            {
                "id": _new_id(),
                "slug": slug,
                "region": "global",
                "name": slug.replace("_", " ").title(),
                "category": "metal",
                "basis_unit": "kg",
                "price_inr_low": cost_low,
                "price_inr_high": cost_high,
                "lead_time_weeks_low": None,
                "lead_time_weeks_high": None,
                "available_in_cities": regional_materials.MATERIAL_AVAILABILITY.get(slug),
                "extras": {
                    "density_kg_m3": spec.get("density_kg_m3"),
                    "yield_mpa": spec.get("yield_mpa"),
                    "ultimate_mpa": spec.get("ultimate_mpa"),
                    "non_magnetic": spec.get("non_magnetic"),
                    "finish_options": spec.get("finish_options", []),
                    "fabrication": spec.get("fabrication", []),
                    "aesthetic": spec.get("aesthetic"),
                },
                "source": "seed:materials.METALS",
            }
        )
    return rows


def _upholstery_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in materials.UPHOLSTERY.items():
        cost_low, cost_high = _band(spec.get("cost_inr_m2"))
        category = "leather" if slug.startswith("leather") else "fabric"
        rows.append(
            {
                "id": _new_id(),
                "slug": slug,
                "region": "global",
                "name": slug.replace("_", " ").title(),
                "category": category,
                "basis_unit": "m2",
                "price_inr_low": cost_low,
                "price_inr_high": cost_high,
                "lead_time_weeks_low": None,
                "lead_time_weeks_high": None,
                "available_in_cities": regional_materials.MATERIAL_AVAILABILITY.get(slug),
                "extras": {
                    "thickness_mm": list(spec["thickness_mm"]) if "thickness_mm" in spec else None,
                    "durability_rubs_k": list(spec["durability_rubs_k"])
                    if "durability_rubs_k" in spec
                    else None,
                    "colourfastness": spec.get("colourfastness"),
                    "notes": spec.get("notes"),
                },
                "source": "seed:materials.UPHOLSTERY",
            }
        )
    return rows


def _foam_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in materials.FOAM.items():
        cost_low, cost_high = _band(spec.get("cost_inr_m3"))
        rows.append(
            {
                "id": _new_id(),
                "slug": slug,
                "region": "global",
                "name": slug.replace("_", " ").title(),
                "category": "foam",
                "basis_unit": "m3",
                "price_inr_low": cost_low,
                "price_inr_high": cost_high,
                "lead_time_weeks_low": None,
                "lead_time_weeks_high": None,
                "available_in_cities": None,
                "extras": {
                    "density_kg_m3": spec.get("density_kg_m3"),
                    "firmness": spec.get("firmness"),
                    "use": spec.get("use"),
                },
                "source": "seed:materials.FOAM",
            }
        )
    return rows


def _finish_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in materials.FINISHES.items():
        cost_low, cost_high = _band(spec.get("cost_inr_m2"))
        rows.append(
            {
                "id": _new_id(),
                "slug": slug,
                "region": "global",
                "name": slug.replace("_", " ").title(),
                "category": "finish",
                "basis_unit": "m2",
                "price_inr_low": cost_low,
                "price_inr_high": cost_high,
                "lead_time_weeks_low": None,
                "lead_time_weeks_high": None,
                "available_in_cities": None,
                "extras": {k: v for k, v in spec.items() if k != "cost_inr_m2"},
                "source": "seed:materials.FINISHES",
            }
        )
    return rows


def material_price_rows() -> list[dict[str, Any]]:
    """All seed rows for ``material_prices``."""
    return [
        *_wood_rows(),
        *_metal_rows(),
        *_upholstery_rows(),
        *_foam_rows(),
        *_finish_rows(),
    ]


# ─────────────────────────────────────────────────────────────────────
# Labor rates
# ─────────────────────────────────────────────────────────────────────


def labor_rate_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade, band in costing.LABOR_RATES_INR_PER_HOUR.items():
        low, high = _band(band)
        rows.append(
            {
                "id": _new_id(),
                "trade": trade,
                "region": "india",
                "rate_inr_per_hour_low": low,
                "rate_inr_per_hour_high": high,
                "notes": "BRD §1C India base — apply city_price_index for regional adjustment.",
                "source": "seed:costing.LABOR_RATES_INR_PER_HOUR",
            }
        )
    return rows


# ─────────────────────────────────────────────────────────────────────
# Trade hours by complexity
# ─────────────────────────────────────────────────────────────────────


# Mirrors cost_engine_service.TRADE_HOURS_BY_COMPLEXITY exactly.
_TRADE_HOURS_BY_COMPLEXITY: dict[str, dict[str, tuple[float, float]]] = {
    "woodworking":   {"simple": (4, 10),  "moderate": (10, 24), "complex": (24, 48), "highly_complex": (48, 96)},
    "welding_metal": {"simple": (2,  6),  "moderate": (6, 16),  "complex": (16, 32), "highly_complex": (32, 60)},
    "upholstery":    {"simple": (4,  8),  "moderate": (8, 20),  "complex": (20, 40), "highly_complex": (40, 80)},
    "finishing":     {"simple": (3,  6),  "moderate": (6, 14),  "complex": (14, 28), "highly_complex": (28, 50)},
    "assembly":      {"simple": (2,  5),  "moderate": (5, 10),  "complex": (10, 20), "highly_complex": (20, 36)},
}


def trade_hour_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for trade, by_level in _TRADE_HOURS_BY_COMPLEXITY.items():
        for level, band in by_level.items():
            low, high = _band(band)
            rows.append(
                {
                    "id": _new_id(),
                    "trade": trade,
                    "complexity": level,
                    "hours_low": low,
                    "hours_high": high,
                    "notes": None,
                    "source": "seed:cost_engine_service.TRADE_HOURS_BY_COMPLEXITY",
                }
            )
    return rows


# ─────────────────────────────────────────────────────────────────────
# City price indices
# ─────────────────────────────────────────────────────────────────────


def city_index_rows() -> list[dict[str, Any]]:
    """One row per canonical city slug, with aliases recorded.

    Notes
    -----
    The legacy dict double-keys some cities (``delhi``/``new_delhi``,
    ``bengaluru``/``bangalore``). We canonicalise on the first form
    encountered and record the rest in ``aliases``.
    """
    canonical_to_aliases: dict[str, list[str]] = {}
    canonical_index: dict[str, float] = {}
    seen_keys: set[str] = set()

    # Detect alias pairs by identical multipliers + co-location in dict.
    pairs = [("delhi", "new_delhi"), ("bengaluru", "bangalore")]

    for canon, alias in pairs:
        if canon in regional_materials.CITY_PRICE_INDEX and alias in regional_materials.CITY_PRICE_INDEX:
            canonical_to_aliases.setdefault(canon, []).append(alias)
            canonical_index[canon] = float(regional_materials.CITY_PRICE_INDEX[canon])
            seen_keys.add(canon)
            seen_keys.add(alias)

    for slug, multiplier in regional_materials.CITY_PRICE_INDEX.items():
        if slug in seen_keys:
            continue
        canonical_index[slug] = float(multiplier)
        canonical_to_aliases.setdefault(slug, [])
        seen_keys.add(slug)

    lt_low, lt_high = _band(regional_materials.REMOTE_LEAD_TIME_ADDER_WEEKS)

    rows: list[dict[str, Any]] = []
    for slug, multiplier in canonical_index.items():
        rows.append(
            {
                "id": _new_id(),
                "city_slug": slug,
                "display_name": slug.replace("_", " ").title(),
                "state": None,
                "tier": _classify_tier(multiplier),
                "index_multiplier": multiplier,
                "remote_lead_time_weeks_low": lt_low,
                "remote_lead_time_weeks_high": lt_high,
                "aliases": canonical_to_aliases.get(slug) or None,
                "source": "seed:regional_materials.CITY_PRICE_INDEX",
            }
        )
    return rows


def _classify_tier(multiplier: float) -> str:
    """Heuristic only — informational column for analytics dashboards."""
    if multiplier >= 1.20:
        return "remote"
    if multiplier >= 1.05:
        return "tier1"
    if multiplier >= 0.98:
        return "tier2"
    return "tier3"


# ─────────────────────────────────────────────────────────────────────
# Cost factors
# ─────────────────────────────────────────────────────────────────────


def cost_factor_rows() -> list[dict[str, Any]]:
    """The BRD §4A constants stored as a simple key/value-band table."""

    def factor(
        key: str,
        band: Any,
        *,
        unit: str = "pct",
        description: str | None = None,
        source: str = "seed:costing",
    ) -> dict[str, Any]:
        low, high = _band(band)
        return {
            "id": _new_id(),
            "factor_key": key,
            "value_low": low,
            "value_high": high,
            "unit": unit,
            "description": description,
            "source": source,
        }

    rows = [
        factor(
            "waste_factor_pct",
            costing.WASTE_FACTOR_PCT,
            description="BRD §1C cutting waste, applied to material subtotal.",
        ),
        factor(
            "finish_cost_pct_of_material",
            costing.FINISH_COST_PCT_OF_MATERIAL,
            description="BRD §1C finish cost as a % of material cost.",
        ),
        factor(
            "hardware_inr_per_piece",
            costing.HARDWARE_INR_PER_PIECE,
            unit="inr_per_piece",
            description="BRD §1C hardware/fittings rate band.",
        ),
        factor(
            "workshop_overhead_pct_of_direct",
            costing.WORKSHOP_OVERHEAD_PCT_OF_DIRECT,
            description="BRD §1C workshop overhead as a % of direct cost.",
        ),
        factor(
            "qc_pct_of_labor",
            costing.QC_PCT_OF_LABOR,
            description="BRD §1C quality control as a % of labor cost.",
        ),
        factor(
            "packaging_logistics_pct_of_product",
            costing.PACKAGING_LOGISTICS_PCT_OF_PRODUCT,
            description="BRD §1C packaging + logistics as a % of product cost.",
        ),
        factor(
            "designer_markup_pct",
            costing.DESIGNER_MARKUP_PCT,
            description="BRD §4B designer markup band when studio resells third-party manufacturing.",
        ),
        factor(
            "designer_margin_pct",
            costing.DESIGNER_MARGIN_PCT,
            description="BRD §4B designer margin alias for outsourced fabrication.",
        ),
        factor(
            "retail_markup_pct",
            costing.RETAIL_MARKUP_PCT,
            description="BRD §4B retail markup band for direct-to-end-client sale.",
        ),
        factor(
            "customization_premium_pct",
            costing.CUSTOMIZATION_PREMIUM_PCT,
            description="BRD §4B customization premium band (overall).",
        ),
    ]

    # Profit margins are segment-specific.
    for segment, band in costing.PROFIT_MARGIN_PCT.items():
        rows.append(
            factor(
                f"profit_margin_pct.{segment}",
                band,
                description=f"BRD §4B profit margin for {segment} segment.",
            )
        )

    # Manufacturer margin by volume tier.
    for tier, band in costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.items():
        rows.append(
            factor(
                f"manufacturer_margin_pct.{tier}",
                band,
                description=f"BRD §4B manufacturer margin for {tier} volume tier.",
            )
        )

    # Customization premium by level.
    for level, band in costing.CUSTOMIZATION_PREMIUM_PCT_BY_LEVEL.items():
        rows.append(
            factor(
                f"customization_premium_pct.{level}",
                band,
                description=f"BRD §4B customization premium — {level}.",
            )
        )

    return rows


# ─────────────────────────────────────────────────────────────────────
# Public — single entry point for the migration
# ─────────────────────────────────────────────────────────────────────


def build_seed_rows() -> dict[str, list[dict[str, Any]]]:
    """All Stage 1 seed rows, keyed by table name.

    Migration usage::

        from app.services.pricing.seed import build_seed_rows

        seed = build_seed_rows()
        op.bulk_insert(material_prices_table, seed["material_prices"])
        ...

    Test usage::

        rows = build_seed_rows()
        assert any(r["slug"] == "walnut" for r in rows["material_prices"])
    """
    return {
        "material_prices": material_price_rows(),
        "labor_rates": labor_rate_rows(),
        "trade_hour_estimates": trade_hour_rows(),
        "city_price_indices": city_index_rows(),
        "cost_factors": cost_factor_rows(),
    }
