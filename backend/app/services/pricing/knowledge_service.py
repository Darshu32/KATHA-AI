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

from app.feeds.fallback import resolve_price_for_material
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


async def load_pricing_bands(
    session: AsyncSession,
    *,
    when: Optional[datetime] = None,
    defaults: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pre-load the BRD Layer 4B pricing-buildup bands from versioned
    ``cost_factors``.

    Returns a dict shaped for the ``pricing_brd`` slot in
    :func:`pricing_service.build_pricing_knowledge`:

    ``{
        "manufacturer_margin_pct_by_volume": {one_off, small_batch, ...},
        "designer_margin_pct_band": [25, 50],
        "retail_markup_pct_band":   [40, 100],
        "customization_premium_pct_by_level": {none, light_finish, ...},
        "customization_premium_pct_band":     [10, 25],
        "profit_margin_pct_by_segment":       {mass_market, luxury},
    }``

    Falls back to caller-supplied defaults per missing key/sub-key.
    """
    defaults = defaults or {}
    flat = await load_cost_factor_bands(
        session,
        [
            "designer_margin_pct",
            "retail_markup_pct",
            "customization_premium_pct",
        ],
        defaults={
            "designer_margin_pct": tuple(
                defaults.get("designer_margin_pct_band") or (25.0, 50.0)
            ),
            "retail_markup_pct": tuple(
                defaults.get("retail_markup_pct_band") or (40.0, 100.0)
            ),
            "customization_premium_pct": tuple(
                defaults.get("customization_premium_pct_band") or (10.0, 25.0)
            ),
        },
        when=when,
    )
    mfg_margin = await load_namespaced_factor_bands(
        session, "manufacturer_margin_pct", when=when
    )
    if not mfg_margin and "manufacturer_margin_pct_by_volume" in defaults:
        mfg_margin = {
            k: list(v)
            for k, v in defaults["manufacturer_margin_pct_by_volume"].items()
        }
    cust_premium = await load_namespaced_factor_bands(
        session, "customization_premium_pct", when=when
    )
    if not cust_premium and "customization_premium_pct_by_level" in defaults:
        cust_premium = {
            k: list(v)
            for k, v in defaults["customization_premium_pct_by_level"].items()
        }
    profit = await load_namespaced_factor_bands(
        session, "profit_margin_pct", when=when
    )
    if not profit and "profit_margin_pct_by_segment" in defaults:
        profit = {
            k: list(v)
            for k, v in defaults["profit_margin_pct_by_segment"].items()
        }
    return {
        "manufacturer_margin_pct_by_volume": mfg_margin,
        "designer_margin_pct_band": flat["designer_margin_pct"],
        "retail_markup_pct_band": flat["retail_markup_pct"],
        "customization_premium_pct_by_level": cust_premium,
        "customization_premium_pct_band": flat["customization_premium_pct"],
        "profit_margin_pct_by_segment": profit,
    }


async def load_sensitivity_bands(
    session: AsyncSession,
    *,
    when: Optional[datetime] = None,
    defaults: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Pre-load the BRD constants the sensitivity-analysis LLM cites.

    Returns ``{
        "manufacturer_margin_pct_by_volume": {...},
        "workshop_overhead_pct_of_direct": [low, high],
        "qc_pct_of_labor": [low, high],
        "packaging_logistics_pct_of_product": [low, high],
    }``.
    """
    defaults = defaults or {}
    flat = await load_cost_factor_bands(
        session,
        [
            "workshop_overhead_pct_of_direct",
            "qc_pct_of_labor",
            "packaging_logistics_pct_of_product",
        ],
        defaults={
            k: tuple(defaults.get(k) or _DEFAULTS_PCT[k])
            for k in (
                "workshop_overhead_pct_of_direct",
                "qc_pct_of_labor",
                "packaging_logistics_pct_of_product",
            )
        },
        when=when,
    )
    mfg_margin = await load_namespaced_factor_bands(
        session, "manufacturer_margin_pct", when=when
    )
    if not mfg_margin and "manufacturer_margin_pct_by_volume" in defaults:
        mfg_margin = {
            k: list(v)
            for k, v in defaults["manufacturer_margin_pct_by_volume"].items()
        }
    return {
        "manufacturer_margin_pct_by_volume": mfg_margin,
        "workshop_overhead_pct_of_direct": flat["workshop_overhead_pct_of_direct"],
        "qc_pct_of_labor": flat["qc_pct_of_labor"],
        "packaging_logistics_pct_of_product": flat[
            "packaging_logistics_pct_of_product"
        ],
    }


async def load_labor_rate_bands(
    session: AsyncSession,
    *,
    when: Optional[datetime] = None,
    defaults: Optional[dict[str, tuple[float, float]]] = None,
) -> dict[str, list[float]]:
    """Return ``{trade: [low, high]}`` for all active labor rates.

    Reads from versioned ``labor_rates`` rows so a price update flows
    through every BRD-citing LLM prompt (cost engine, parametric design,
    manufacturing spec, knowledge integration) without code changes.
    Falls back to a caller-supplied default per trade when the row is
    missing — keeps dev environments running on the seed values.
    """
    when = when or datetime.now(timezone.utc)
    labor_repo = LaborRateRepository(session)
    rows = await labor_repo.list_active(when=when)
    out: dict[str, list[float]] = {
        r["trade"]: [
            float(r["rate_inr_per_hour_low"]),
            float(r["rate_inr_per_hour_high"]),
        ]
        for r in rows
    }
    if defaults:
        for trade, (lo, hi) in defaults.items():
            out.setdefault(trade, [float(lo), float(hi)])
    return out


async def load_namespaced_factor_bands(
    session: AsyncSession,
    prefix: str,
    *,
    when: Optional[datetime] = None,
) -> dict[str, list[float]]:
    """Return ``{sub_key: [low, high]}`` for all rows whose ``factor_key``
    matches ``{prefix}.{sub_key}``.

    Used for grouped bands like ``manufacturer_margin_pct.*`` and
    ``customization_premium_pct.*`` where each level has its own row.
    """
    when = when or datetime.now(timezone.utc)
    factor_repo = CostFactorRepository(session)
    rows = await factor_repo.list_active(when=when)
    out: dict[str, list[float]] = {}
    needle = f"{prefix}."
    for r in rows:
        k = r["factor_key"]
        if not k.startswith(needle):
            continue
        sub = k[len(needle):]
        if not sub or "." in sub:
            continue
        out[sub] = [float(r["value_low"]), float(r["value_high"])]
    return out


async def load_cost_factor_bands(
    session: AsyncSession,
    keys: list[str],
    *,
    when: Optional[datetime] = None,
    defaults: Optional[dict[str, tuple[float, float]]] = None,
) -> dict[str, list[float]]:
    """Return ``{key: [low, high]}`` for the requested factor keys.

    Reads from versioned ``cost_factors`` rows so a price edit through
    the admin UI flows into every consumer (cost engine + cost-breakdown
    LLM + material-spec LLM). Falls back to a per-key default tuple when
    the row is missing — same defensive pattern as
    :func:`build_pricing_knowledge` so a fresh dev DB doesn't break the
    flow before seed rows land.
    """
    when = when or datetime.now(timezone.utc)
    factor_repo = CostFactorRepository(session)
    rows = await factor_repo.list_active(when=when)
    by_key: dict[str, dict[str, Any]] = {r["factor_key"]: r for r in rows}

    fallback = {**_DEFAULTS_PCT, **_DEFAULTS_INR, **(defaults or {})}
    out: dict[str, list[float]] = {}
    for k in keys:
        row = by_key.get(k)
        if row is not None:
            out[k] = [float(row["value_low"]), float(row["value_high"])]
        elif k in fallback:
            lo, hi = fallback[k]
            out[k] = [float(lo), float(hi)]
        # else: omitted — caller can decide how to handle missing keys
    return out


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
    # Stage 12: every band is run through the fallback chain (live →
    # cached → seed → unavailable) so live MCX/vendor quotes override
    # the seed value when fresh enough. The chain returns a uniform
    # ``ResolvedPrice`` with a ``tier`` + ``freshness`` envelope which
    # we record into ``source_versions`` for the transparency banner.
    materials = await mat_repo.list_active(when=when)
    wood_inr_kg: dict[str, list[float]] = {}
    metals_inr_kg: dict[str, list[float]] = {}
    upholstery_inr_m2: dict[str, list[float]] = {}
    foam_inr_m3: dict[str, list[float]] = {}
    finishes_inr_m2: dict[str, list[float]] = {}
    material_freshness: dict[str, dict[str, Any]] = {}

    for m in materials:
        slug = m["slug"]
        category = m["category"]
        resolved = await resolve_price_for_material(
            session,
            material_slug=slug,
            region="global",
            when=when,
        )
        if resolved.available:
            band = [resolved.price_low, resolved.price_high]
        else:
            band = [m["price_inr_low"], m["price_inr_high"]]
        material_freshness[slug] = {
            "tier": resolved.tier,
            "freshness": resolved.freshness,
            "source": resolved.source or m["source"],
            "quote_id": resolved.quote_id,
        }
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
            m["slug"]: {
                "id": m["id"],
                "version": m["version"],
                "source": m["source"],
                **material_freshness.get(m["slug"], {}),
            }
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
