"""DB-backed cost-engine knowledge builder.

Replaces the hardcoded `build_cost_engine_knowledge` previously living
in `cost_engine_service.py`. Assembles the *exact same shape* the LLM
prompt expects, but pulls every value from versioned DB rows instead
of Python literals.

Key shape (must match the cost-engine system prompt):

    {
      "project": {...},
      "cost_brd": {
          "waste_factor_pct_band": [10, 15],
          "finish_cost_pct_of_material": [15, 25],
          "hardware_inr_per_piece": [500, 2000],
          "labor_rates_inr_hour": {"woodworking": [200, 400], ...},
          "trade_hours_by_complexity": {...},
          "workshop_overhead_pct_of_direct": [30, 40],
          "qc_pct_of_labor": [5, 10],
          "packaging_logistics_pct_of_product": [10, 15],
          ...
      },
      "materials_kb": {
          "wood_inr_kg": {"walnut": [500, 800], ...},
          "metals_inr_kg": {"mild_steel": [60, 90], ...},
      },
      "city_price_index": 1.18,
      "source_versions": {...},   ← NEW in Stage 1: provenance per row
    }

The ``source_versions`` dict is what enables Stage 11 (transparency):
every value cited by the LLM can be traced to a specific row id +
version + ``source`` tag.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.pricing import (
    CityPriceIndexRepository,
    CostFactorRepository,
    LaborRateRepository,
    MaterialPriceRepository,
    TradeHourRepository,
)


# ─────────────────────────────────────────────────────────────────────
# Defaults (match the legacy hardcoded values)
# ─────────────────────────────────────────────────────────────────────
#
# These are the BRD constants. They're fall-backs only — the real
# source of truth is the ``cost_factors`` table seeded by 0003. We
# include them here so the cost engine still produces sensible output
# during the transition window where DB rows might be missing (eg. a
# fresh dev DB before seed migration runs).

_DEFAULTS_PCT: dict[str, tuple[float, float]] = {
    "waste_factor_pct": (10.0, 15.0),
    "finish_cost_pct_of_material": (15.0, 25.0),
    "workshop_overhead_pct_of_direct": (30.0, 40.0),
    "qc_pct_of_labor": (5.0, 10.0),
    "packaging_logistics_pct_of_product": (10.0, 15.0),
}
_DEFAULTS_INR: dict[str, tuple[float, float]] = {
    "hardware_inr_per_piece": (500.0, 2000.0),
}


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


async def build_pricing_knowledge(
    session: AsyncSession,
    *,
    project_name: str,
    piece_name: str,
    theme: str,
    city: Optional[str],
    market_segment: str,
    complexity: str,
    hardware_piece_count: int,
    parametric_spec: Optional[dict[str, Any]] = None,
    material_spec: Optional[dict[str, Any]] = None,
    manufacturing_spec: Optional[dict[str, Any]] = None,
    overrides: Optional[list[dict[str, Any]]] = None,
    when: Optional[datetime] = None,
) -> dict[str, Any]:
    """Build the cost-engine knowledge dict from versioned DB rows.

    The dict is **deterministic for a given ``when``** — pass an
    explicit timestamp when reproducing a historical estimate so prices
    that were active *then* are returned (Stage 1's whole point).
    """
    when = when or datetime.now(timezone.utc)

    factor_repo = CostFactorRepository(session)
    labor_repo = LaborRateRepository(session)
    hours_repo = TradeHourRepository(session)
    city_repo = CityPriceIndexRepository(session)
    mat_repo = MaterialPriceRepository(session)

    # ── Cost factors ──────────────────────────────────────────────────
    factors = await factor_repo.list_active(when=when)
    factor_by_key: dict[str, dict[str, Any]] = {f["factor_key"]: f for f in factors}

    def _band_or_default(key: str, default: tuple[float, float]) -> list[float]:
        f = factor_by_key.get(key)
        if f is None:
            return list(default)
        return [float(f["value_low"]), float(f["value_high"])]

    pct_bands = {
        key: _band_or_default(key, default)
        for key, default in _DEFAULTS_PCT.items()
    }
    inr_bands = {
        key: _band_or_default(key, default)
        for key, default in _DEFAULTS_INR.items()
    }

    # ── Labor rates ───────────────────────────────────────────────────
    labor_rows = await labor_repo.list_active(when=when)
    labor_rates_inr_hour: dict[str, list[float]] = {
        r["trade"]: [r["rate_inr_per_hour_low"], r["rate_inr_per_hour_high"]]
        for r in labor_rows
    }

    # ── Trade hours ───────────────────────────────────────────────────
    hour_rows = await hours_repo.list_active(when=when)
    trade_hours_by_complexity: dict[str, dict[str, list[float]]] = {}
    for r in hour_rows:
        trade_hours_by_complexity.setdefault(r["trade"], {})[r["complexity"]] = [
            r["hours_low"],
            r["hours_high"],
        ]

    # ── City price index ──────────────────────────────────────────────
    city_row = await city_repo.resolve(city, when=when)
    city_index = float(city_row["index_multiplier"]) if city_row else 1.0

    # ── Materials KB ──────────────────────────────────────────────────
    materials = await mat_repo.list_active(when=when)
    wood_inr_kg: dict[str, list[float]] = {}
    metals_inr_kg: dict[str, list[float]] = {}
    upholstery_inr_m2: dict[str, list[float]] = {}
    foam_inr_m3: dict[str, list[float]] = {}
    finishes_inr_m2: dict[str, list[float]] = {}

    for m in materials:
        band = [m["price_inr_low"], m["price_inr_high"]]
        category = m["category"]
        slug = m["slug"]
        if category in {"wood_solid", "wood_panel"} and m["basis_unit"] == "kg":
            wood_inr_kg[slug] = band
        elif category == "metal" and m["basis_unit"] == "kg":
            metals_inr_kg[slug] = band
        elif category in {"leather", "fabric"} and m["basis_unit"] == "m2":
            upholstery_inr_m2[slug] = band
        elif category == "foam" and m["basis_unit"] == "m3":
            foam_inr_m3[slug] = band
        elif category == "finish":
            finishes_inr_m2[slug] = band

    # ── Source versions for Stage 11 transparency ─────────────────────
    source_versions: dict[str, Any] = {
        "captured_at": when.isoformat(),
        "city_price_index": (
            {"id": city_row["id"], "version": city_row["version"], "source": city_row["source"]}
            if city_row
            else {"id": None, "version": None, "source": "default:1.0"}
        ),
        "cost_factors": {
            f["factor_key"]: {"id": f["id"], "version": f["version"], "source": f["source"]}
            for f in factors
        },
        "labor_rates": {
            r["trade"]: {"id": r["id"], "version": r["version"], "source": r["source"]}
            for r in labor_rows
        },
        "trade_hours": {
            f"{r['trade']}.{r['complexity']}": {
                "id": r["id"],
                "version": r["version"],
                "source": r["source"],
            }
            for r in hour_rows
        },
        "materials": {
            m["slug"]: {"id": m["id"], "version": m["version"], "source": m["source"]}
            for m in materials
        },
    }

    # ── Assemble the knowledge dict ───────────────────────────────────
    return {
        "project": {
            "name": project_name,
            "piece_name": piece_name,
            "theme": theme or None,
            "city": city or None,
            "city_price_index": city_index,
            "market_segment": market_segment.lower(),
            "complexity": complexity.lower(),
            "hardware_piece_count": hardware_piece_count,
            "overrides": overrides or [],
        },
        "parametric_spec": parametric_spec or {},
        "material_spec": material_spec or {},
        "manufacturing_spec": manufacturing_spec or {},
        "cost_brd": {
            "waste_factor_pct_band": pct_bands["waste_factor_pct"],
            "finish_cost_pct_of_material": pct_bands["finish_cost_pct_of_material"],
            "hardware_inr_per_piece": inr_bands["hardware_inr_per_piece"],
            "workshop_overhead_pct_of_direct": pct_bands["workshop_overhead_pct_of_direct"],
            "qc_pct_of_labor": pct_bands["qc_pct_of_labor"],
            "packaging_logistics_pct_of_product": pct_bands[
                "packaging_logistics_pct_of_product"
            ],
            "labor_rates_inr_hour": labor_rates_inr_hour,
            "trade_hours_by_complexity": trade_hours_by_complexity,
        },
        "materials_kb": {
            "wood_inr_kg": wood_inr_kg,
            "metals_inr_kg": metals_inr_kg,
            "upholstery_inr_m2": upholstery_inr_m2,
            "foam_inr_m3": foam_inr_m3,
            "finishes_inr_m2": finishes_inr_m2,
        },
        "source_versions": source_versions,
    }
