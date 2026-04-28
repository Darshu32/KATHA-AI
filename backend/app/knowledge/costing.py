"""Cost modelling rules (BRD 1C — Cost Modeling).

This module centralises cost-computation factors used by estimation and
by the architect-brief LLM when it reasons about budgets.

BRD 1C — Material Cost Calculation
  • Linear / area-based: kg or m² × unit price
  • Waste factor: 10–15 % for cutting
  • Finish cost: 15–25 % of material cost
  • Hardware / fittings: ₹500–2 000 per piece

Values are ranges unless noted. Helpers are deterministic, pure — they
never hit the network and never read from the database. Regional price
scaling is layered on top by knowledge.regional_materials.
"""

from __future__ import annotations

# ── BRD rollup constant the LLM can cite verbatim ───────────────────────────
MATERIAL_COST_BRD_SPEC: dict = {
    "basis": ("kg", "m2"),                          # linear/area-based
    "waste_factor_pct": (10, 15),                    # % material wastage from cutting
    "finish_cost_pct_of_material": (15, 25),         # % of material cost
    "hardware_fittings_inr_per_piece": (500, 2000),  # ₹/piece
}

# ── Parameter bands as first-class constants ────────────────────────────────
WASTE_FACTOR_PCT: tuple[float, float] = (10.0, 15.0)
FINISH_COST_PCT_OF_MATERIAL: tuple[float, float] = (15.0, 25.0)
HARDWARE_INR_PER_PIECE: tuple[int, int] = (500, 2000)

# Unit-of-measure basis per material family. Picks what the estimator
# multiplies by: mass (kg) for solids, area (m²) for sheets and uphol.
COST_BASIS_BY_FAMILY: dict[str, str] = {
    "wood_solid": "kg",
    "wood_panel": "m2",
    "metal": "kg",
    "stone": "m2",
    "glass": "m2",
    "leather": "m2",
    "fabric": "m2",
    "foam": "m3",
    "tile": "m2",
    "finish": "m2",
}


def _midpoint(band: tuple[float, float]) -> float:
    lo, hi = band
    return (lo + hi) / 2.0


def _mid_int(band: tuple[int, int]) -> int:
    return int(round(_midpoint(band)))


def material_cost_with_waste(
    *,
    quantity: float,
    unit_rate_inr: float,
    waste_factor_pct: float | None = None,
) -> dict:
    """Quantity × unit-rate scaled up by cutting waste.

    Returned as a band (low / mid / high) using the BRD 10–15 % spread,
    unless caller pins `waste_factor_pct` to a specific value.
    """
    if quantity < 0 or unit_rate_inr < 0:
        raise ValueError("quantity and unit_rate_inr must be non-negative")

    base = quantity * unit_rate_inr
    if waste_factor_pct is not None:
        multiplier = 1.0 + (waste_factor_pct / 100.0)
        total = base * multiplier
        return {
            "base_cost_inr": round(base, 2),
            "waste_factor_pct": waste_factor_pct,
            "total_cost_inr": round(total, 2),
        }

    lo_pct, hi_pct = WASTE_FACTOR_PCT
    return {
        "base_cost_inr": round(base, 2),
        "waste_factor_pct_band": WASTE_FACTOR_PCT,
        "total_cost_inr": {
            "low": round(base * (1.0 + lo_pct / 100.0), 2),
            "mid": round(base * (1.0 + _midpoint(WASTE_FACTOR_PCT) / 100.0), 2),
            "high": round(base * (1.0 + hi_pct / 100.0), 2),
        },
    }


def finish_cost(material_cost_inr: float) -> dict:
    """Finish cost as BRD 15–25 % of material cost."""
    if material_cost_inr < 0:
        raise ValueError("material_cost_inr must be non-negative")
    lo_pct, hi_pct = FINISH_COST_PCT_OF_MATERIAL
    return {
        "material_cost_inr": round(material_cost_inr, 2),
        "finish_pct_band": FINISH_COST_PCT_OF_MATERIAL,
        "finish_cost_inr": {
            "low": round(material_cost_inr * lo_pct / 100.0, 2),
            "mid": round(material_cost_inr * _midpoint(FINISH_COST_PCT_OF_MATERIAL) / 100.0, 2),
            "high": round(material_cost_inr * hi_pct / 100.0, 2),
        },
    }


def hardware_cost(piece_count: int) -> dict:
    """Hardware / fittings rollup at ₹500–2 000 per piece (BRD)."""
    if piece_count < 0:
        raise ValueError("piece_count must be non-negative")
    lo, hi = HARDWARE_INR_PER_PIECE
    return {
        "piece_count": piece_count,
        "rate_inr_per_piece_band": HARDWARE_INR_PER_PIECE,
        "total_cost_inr": {
            "low": lo * piece_count,
            "mid": _mid_int(HARDWARE_INR_PER_PIECE) * piece_count,
            "high": hi * piece_count,
        },
    }


# ── BRD 1C — Labor Cost (India context) ─────────────────────────────────────
#   Woodworking:     ₹200–400 /hour skilled
#   Welding / metal: ₹150–300 /hour
#   Upholstery:      ₹100–200 /hour
#   Finishing:       ₹100–150 /hour
#   Assembly:        ₹ 50–100 /hour
# Multiply by city_price_index from knowledge.regional_materials for
# Mumbai (1.18), Bengaluru (1.10), Leh (1.40), etc.
LABOR_RATES_INR_PER_HOUR: dict[str, tuple[int, int]] = {
    "woodworking": (200, 400),
    "welding_metal": (150, 300),
    "upholstery": (100, 200),
    "finishing": (100, 150),
    "assembly": (50, 100),
}

LABOR_COST_BRD_SPEC: dict = {
    "context": "India base rates — apply city price index for regional adjustment",
    "rates_inr_hour": dict(LABOR_RATES_INR_PER_HOUR),
}


def labor_cost(
    *,
    trade: str,
    hours: float,
    city_price_index: float = 1.0,
) -> dict:
    """Hours × hourly rate (band) × regional price index.

    `trade` must be one of LABOR_RATES_INR_PER_HOUR keys.
    `city_price_index` defaults to 1.0 (Tier-1 baseline). Pull live values
    from `knowledge.regional_materials.price_index_for_city`.
    """
    if hours < 0:
        raise ValueError("hours must be non-negative")
    if city_price_index <= 0:
        raise ValueError("city_price_index must be positive")
    rate_band = LABOR_RATES_INR_PER_HOUR.get(trade)
    if rate_band is None:
        raise ValueError(
            f"Unknown trade '{trade}'. Known: {sorted(LABOR_RATES_INR_PER_HOUR)}"
        )

    lo, hi = rate_band
    mid = _midpoint(rate_band)
    return {
        "trade": trade,
        "hours": hours,
        "city_price_index": city_price_index,
        "base_rate_inr_hour_band": rate_band,
        "effective_rate_inr_hour": {
            "low": round(lo * city_price_index, 2),
            "mid": round(mid * city_price_index, 2),
            "high": round(hi * city_price_index, 2),
        },
        "total_cost_inr": {
            "low": round(lo * hours * city_price_index, 2),
            "mid": round(mid * hours * city_price_index, 2),
            "high": round(hi * hours * city_price_index, 2),
        },
    }


def labor_cost_breakdown(
    *,
    hours_by_trade: dict[str, float],
    city_price_index: float = 1.0,
) -> dict:
    """Roll up multiple trades into a single labor cost band."""
    lines: list[dict] = []
    grand = {"low": 0.0, "mid": 0.0, "high": 0.0}
    for trade, hours in hours_by_trade.items():
        line = labor_cost(trade=trade, hours=hours, city_price_index=city_price_index)
        lines.append(line)
        grand["low"] += line["total_cost_inr"]["low"]
        grand["mid"] += line["total_cost_inr"]["mid"]
        grand["high"] += line["total_cost_inr"]["high"]
    return {
        "city_price_index": city_price_index,
        "lines": lines,
        "grand_total_inr": {k: round(v, 2) for k, v in grand.items()},
    }


# ── BRD 1C — Overhead & Margin ──────────────────────────────────────────────
#   Workshop overhead:    30–40 % of direct costs (material + labor)
#   Packaging & logistics: 10–15 % of product cost (post-overhead)
#   Profit margin:        40–60 % (luxury) | 30–40 % (mass market)
#   Designer markup:      25–50 % (applied if studio is not the manufacturer)
WORKSHOP_OVERHEAD_PCT_OF_DIRECT: tuple[float, float] = (30.0, 40.0)
QC_PCT_OF_LABOR: tuple[float, float] = (5.0, 10.0)
PACKAGING_LOGISTICS_PCT_OF_PRODUCT: tuple[float, float] = (10.0, 15.0)
PROFIT_MARGIN_PCT: dict[str, tuple[float, float]] = {
    "luxury": (40.0, 60.0),
    "mass_market": (30.0, 40.0),
}
DESIGNER_MARKUP_PCT: tuple[float, float] = (25.0, 50.0)
DESIGNER_MARGIN_PCT: tuple[float, float] = (25.0, 50.0)         # BRD 4B alias — same band, applied when studio outsources fabrication.

# BRD 4B — Manufacturer margin band by production volume tier.
# Lower volumes carry the higher margin; mass production amortises tooling
# and labour across many units so the band tightens to the lower end.
MANUFACTURER_MARGIN_PCT_BY_VOLUME: dict[str, tuple[float, float]] = {
    "one_off":         (50.0, 60.0),  # bespoke, single-piece
    "small_batch":     (40.0, 55.0),  # 5–25 units
    "production":      (35.0, 45.0),  # 25–250 units
    "mass_production": (30.0, 40.0),  # 250+ units
}

# BRD 4B — Retail markup applied when the studio sells direct to end-client
# rather than through a trade channel.
RETAIL_MARKUP_PCT: tuple[float, float] = (40.0, 100.0)

# BRD 4B — Customization premium for non-catalogue work.
CUSTOMIZATION_PREMIUM_PCT_BY_LEVEL: dict[str, tuple[float, float]] = {
    "none":             (0.0,  0.0),
    "light_finish":     (5.0, 10.0),   # bespoke colour/finish only
    "moderate":        (10.0, 15.0),   # bespoke dimensions or material on a catalogue piece
    "heavy":           (15.0, 20.0),   # bespoke joinery or hardware
    "fully_bespoke":   (20.0, 25.0),   # one-of-one design
}
CUSTOMIZATION_PREMIUM_PCT: tuple[float, float] = (10.0, 25.0)

OVERHEAD_MARGIN_BRD_SPEC: dict = {
    "workshop_overhead_pct_of_direct": WORKSHOP_OVERHEAD_PCT_OF_DIRECT,
    "qc_pct_of_labor": QC_PCT_OF_LABOR,
    "packaging_logistics_pct_of_product": PACKAGING_LOGISTICS_PCT_OF_PRODUCT,
    "profit_margin_pct": PROFIT_MARGIN_PCT,
    "designer_markup_pct": DESIGNER_MARKUP_PCT,
    "designer_margin_pct": DESIGNER_MARGIN_PCT,
    "manufacturer_margin_pct_by_volume": MANUFACTURER_MARGIN_PCT_BY_VOLUME,
    "retail_markup_pct": RETAIL_MARKUP_PCT,
    "customization_premium_pct_by_level": CUSTOMIZATION_PREMIUM_PCT_BY_LEVEL,
    "customization_premium_pct_band": CUSTOMIZATION_PREMIUM_PCT,
    "designer_markup_applies_when": "studio resells third-party manufacturing",
}


def _band_apply(value: float, pct_band: tuple[float, float]) -> dict:
    lo, hi = pct_band
    return {
        "low": round(value * lo / 100.0, 2),
        "mid": round(value * _midpoint(pct_band) / 100.0, 2),
        "high": round(value * hi / 100.0, 2),
    }


def price_buildup(
    *,
    direct_cost_inr: float,
    market_segment: str = "mass_market",
    apply_designer_markup: bool = False,
) -> dict:
    """Build sell-price from direct cost using BRD overhead + margin bands.

    Stack (each step folds the BRD percentage band onto the running total):
      1. direct_cost  →  + workshop_overhead (30–40 % of direct)
      2.            →  + packaging_logistics (10–15 % of product)
      3.            →  + profit_margin (segment-specific band)
      4. (optional) →  + designer_markup (25–50 % on the trade price)

    Returned as low / mid / high bands at every layer so the LLM can
    cite full price walks the way an architect priced a deal.
    """
    if direct_cost_inr < 0:
        raise ValueError("direct_cost_inr must be non-negative")
    margin_band = PROFIT_MARGIN_PCT.get(market_segment.lower())
    if margin_band is None:
        raise ValueError(
            f"Unknown market_segment '{market_segment}'. Known: {sorted(PROFIT_MARGIN_PCT)}"
        )

    overhead = _band_apply(direct_cost_inr, WORKSHOP_OVERHEAD_PCT_OF_DIRECT)
    product_cost = {k: round(direct_cost_inr + v, 2) for k, v in overhead.items()}

    pack = {k: _band_apply(v, PACKAGING_LOGISTICS_PCT_OF_PRODUCT)[k] for k, v in product_cost.items()}
    landed = {k: round(product_cost[k] + pack[k], 2) for k in landed_keys() }

    margin = {k: _band_apply(v, margin_band)[k] for k, v in landed.items()}
    trade_price = {k: round(landed[k] + margin[k], 2) for k in landed_keys()}

    result: dict = {
        "direct_cost_inr": round(direct_cost_inr, 2),
        "workshop_overhead_inr": overhead,
        "product_cost_inr": product_cost,
        "packaging_logistics_inr": pack,
        "landed_cost_inr": landed,
        "market_segment": market_segment.lower(),
        "profit_margin_pct_band": margin_band,
        "profit_margin_inr": margin,
        "trade_price_inr": trade_price,
    }

    if apply_designer_markup:
        markup = {k: _band_apply(v, DESIGNER_MARKUP_PCT)[k] for k, v in trade_price.items()}
        retail_price = {k: round(trade_price[k] + markup[k], 2) for k in landed_keys()}
        result["designer_markup_pct_band"] = DESIGNER_MARKUP_PCT
        result["designer_markup_inr"] = markup
        result["retail_price_inr"] = retail_price

    return result


def landed_keys() -> tuple[str, ...]:
    return ("low", "mid", "high")


# ── BRD 1C — Pricing Formula (canonical) ────────────────────────────────────
#   Final Price = (Material + Labor + Overhead) × (1 + Margin %)
#   Example:    (₹5 000 + ₹2 000 + ₹2 800) × 1.5 = ₹14 700
#
# Notes:
#   • "Overhead" here is workshop overhead in absolute INR — caller
#     resolves it via WORKSHOP_OVERHEAD_PCT_OF_DIRECT band if needed.
#   • Margin % is expressed as a fraction (0.50 == 50 %).
#   • For the richer multi-layer price walk that adds packaging,
#     logistics, and designer markup, see `price_buildup()`.
PRICING_FORMULA_BRD: dict = {
    "formula": "Final Price = (Material + Labor + Overhead) × (1 + Margin %)",
    "example": {
        "material_inr": 5000,
        "labor_inr": 2000,
        "overhead_inr": 2800,
        "margin_pct": 50,
        "expected_final_inr": 14700,
    },
}


def final_price(
    *,
    material_inr: float,
    labor_inr: float,
    overhead_inr: float,
    margin_pct: float,
) -> dict:
    """Apply the BRD 1C canonical pricing formula.

    Final Price = (Material + Labor + Overhead) × (1 + Margin %)

    `margin_pct` is a percentage (e.g. 50 for +50 %), not a fraction.
    """
    for name, value in (
        ("material_inr", material_inr),
        ("labor_inr", labor_inr),
        ("overhead_inr", overhead_inr),
    ):
        if value < 0:
            raise ValueError(f"{name} must be non-negative (got {value})")
    if margin_pct < 0:
        raise ValueError("margin_pct must be non-negative")

    direct_plus_overhead = material_inr + labor_inr + overhead_inr
    multiplier = 1.0 + (margin_pct / 100.0)
    final = direct_plus_overhead * multiplier
    return {
        "formula": PRICING_FORMULA_BRD["formula"],
        "material_inr": round(material_inr, 2),
        "labor_inr": round(labor_inr, 2),
        "overhead_inr": round(overhead_inr, 2),
        "subtotal_inr": round(direct_plus_overhead, 2),
        "margin_pct": margin_pct,
        "margin_multiplier": multiplier,
        "final_price_inr": round(final, 2),
    }


def final_price_band(
    *,
    material_inr: float,
    labor_inr: float,
    overhead_pct_of_direct: tuple[float, float] | None = None,
    market_segment: str = "mass_market",
) -> dict:
    """BRD canonical formula resolved against the BRD overhead + margin bands.

    Computes low / mid / high final prices by combining:
      • overhead band (default WORKSHOP_OVERHEAD_PCT_OF_DIRECT  = 30–40 %)
      • margin band   (PROFIT_MARGIN_PCT[market_segment])
    """
    overhead_band = overhead_pct_of_direct or WORKSHOP_OVERHEAD_PCT_OF_DIRECT
    margin_band = PROFIT_MARGIN_PCT.get(market_segment.lower())
    if margin_band is None:
        raise ValueError(
            f"Unknown market_segment '{market_segment}'. Known: {sorted(PROFIT_MARGIN_PCT)}"
        )

    direct = material_inr + labor_inr
    overhead_low = direct * overhead_band[0] / 100.0
    overhead_high = direct * overhead_band[1] / 100.0
    overhead_mid = direct * _midpoint(overhead_band) / 100.0

    def _walk(overhead_value: float, margin_value: float) -> float:
        return (material_inr + labor_inr + overhead_value) * (1.0 + margin_value / 100.0)

    return {
        "formula": PRICING_FORMULA_BRD["formula"],
        "market_segment": market_segment.lower(),
        "overhead_pct_band": overhead_band,
        "margin_pct_band": margin_band,
        "overhead_inr": {
            "low": round(overhead_low, 2),
            "mid": round(overhead_mid, 2),
            "high": round(overhead_high, 2),
        },
        "final_price_inr": {
            "low": round(_walk(overhead_low, margin_band[0]), 2),
            "mid": round(_walk(overhead_mid, _midpoint(margin_band)), 2),
            "high": round(_walk(overhead_high, margin_band[1]), 2),
        },
    }


def material_cost_rollup(
    *,
    quantity: float,
    unit_rate_inr: float,
    hardware_piece_count: int = 0,
) -> dict:
    """End-to-end material-stage cost per BRD 1C.

    Combines:  base → + waste (10–15 %) → + finish (15–25 % of material)
              → + hardware (₹500–2 000 × pieces).
    """
    material = material_cost_with_waste(quantity=quantity, unit_rate_inr=unit_rate_inr)
    mat_mid = material["total_cost_inr"]["mid"]
    finish = finish_cost(mat_mid)
    hw = hardware_cost(hardware_piece_count)

    return {
        "basis": "kg_or_m2 × unit_rate",
        "material": material,
        "finish": finish,
        "hardware": hw,
        "grand_total_inr": {
            "low": round(material["total_cost_inr"]["low"] + finish["finish_cost_inr"]["low"] + hw["total_cost_inr"]["low"], 2),
            "mid": round(material["total_cost_inr"]["mid"] + finish["finish_cost_inr"]["mid"] + hw["total_cost_inr"]["mid"], 2),
            "high": round(material["total_cost_inr"]["high"] + finish["finish_cost_inr"]["high"] + hw["total_cost_inr"]["high"], 2),
        },
    }
