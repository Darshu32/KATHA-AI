"""LLM-driven Markup & Pricing service (BRD Layer 4B).

Layered on top of the LAYER-4A cost engine. Takes TOTAL MANUFACTURING
COST and walks it through the BRD margin / markup stack to the FINAL
RETAIL PRICE that goes on the client invoice.

Pipeline contract — same as every other LLM service:

    INPUT (manufacturing_cost_inr + settings: outsourcing flag, volume
           tier, sales channel, customization level, market segment)
      → INJECT  (BRD margin/markup constants — manufacturer margin
                 30–60 % by volume, designer margin 25–50 %, retail
                 markup 40–100 %, customization premium 10–25 %)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (every layer is the right base × the right band; the
                   final retail price reconciles end-to-end)
      → OUTPUT  (pricing_buildup JSON conforming to the BRD template)

The order of layers reflects how a real practice walks the price:
    manufacturing_cost
      → + manufacturer_margin   (always)
      = ex_factory_price
      → + designer_margin       (only if studio outsources fabrication)
      = trade_price
      → + retail_markup         (only if selling direct to end-client)
      = retail_base
      → + customization_premium (if bespoke level > none)
      = FINAL RETAIL PRICE
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import costing, themes

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None


def _client_instance() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
    return _client


# ── Vocabularies ────────────────────────────────────────────────────────────
VOLUME_TIERS_IN_SCOPE = tuple(costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.keys())
CUSTOMIZATION_LEVELS_IN_SCOPE = tuple(costing.CUSTOMIZATION_PREMIUM_PCT_BY_LEVEL.keys())
MARKET_SEGMENTS_IN_SCOPE = ("mass_market", "luxury")
SALES_CHANNELS_IN_SCOPE = ("trade", "retail_direct", "ecommerce", "showroom")


# ── Request schema ──────────────────────────────────────────────────────────


class PricingRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    piece_name: str = Field(default="Primary piece", max_length=160)
    theme: str = Field(default="", max_length=64)
    manufacturing_cost_inr: float = Field(gt=0, le=1e9)
    cost_engine: dict[str, Any] | None = None
    market_segment: str = Field(default="mass_market")
    volume_tier: str = Field(default="small_batch")
    sales_channel: str = Field(default="trade")
    customization_level: str = Field(default="none")
    studio_outsources_fabrication: bool = Field(default=False)
    selling_direct_to_end_client: bool = Field(default=False)
    city: str = Field(default="", max_length=80)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def build_pricing_knowledge(req: PricingRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) if req.theme else None
    return {
        "project": {
            "name": req.project_name,
            "piece_name": req.piece_name,
            "theme": req.theme or None,
            "city": req.city or None,
            "market_segment": req.market_segment.lower(),
            "volume_tier": req.volume_tier.lower(),
            "sales_channel": req.sales_channel.lower(),
            "customization_level": req.customization_level.lower(),
            "studio_outsources_fabrication": req.studio_outsources_fabrication,
            "selling_direct_to_end_client": req.selling_direct_to_end_client,
            "manufacturing_cost_inr": req.manufacturing_cost_inr,
        },
        "theme_rule_pack": (
            {"display_name": (pack or {}).get("display_name") or req.theme}
            if pack else None
        ),
        "cost_engine": req.cost_engine or {},
        "pricing_brd": {
            "manufacturer_margin_pct_by_volume": {
                k: list(v) for k, v in costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.items()
            },
            "designer_margin_pct_band": list(costing.DESIGNER_MARGIN_PCT),
            "retail_markup_pct_band": list(costing.RETAIL_MARKUP_PCT),
            "customization_premium_pct_by_level": {
                k: list(v) for k, v in costing.CUSTOMIZATION_PREMIUM_PCT_BY_LEVEL.items()
            },
            "customization_premium_pct_band": list(costing.CUSTOMIZATION_PREMIUM_PCT),
            "profit_margin_pct_by_segment": {
                k: list(v) for k, v in costing.PROFIT_MARGIN_PCT.items()
            },
            "pricing_formula_brd": dict(costing.PRICING_FORMULA_BRD),
            "designer_markup_applies_when": (
                costing.OVERHEAD_MARGIN_BRD_SPEC.get("designer_markup_applies_when")
            ),
        },
        "vocab": {
            "volume_tiers_in_scope": list(VOLUME_TIERS_IN_SCOPE),
            "customization_levels_in_scope": list(CUSTOMIZATION_LEVELS_IN_SCOPE),
            "market_segments_in_scope": list(MARKET_SEGMENTS_IN_SCOPE),
            "sales_channels_in_scope": list(SALES_CHANNELS_IN_SCOPE),
        },
    }


# ── System prompt ───────────────────────────────────────────────────────────


PRICING_SYSTEM_PROMPT = """You are a senior studio principal walking the price from TOTAL MANUFACTURING COST to FINAL RETAIL PRICE for a single piece (BRD Layer 4B).

Read the [KNOWLEDGE] block — pricing BRD constants (manufacturer margin 30–60 % banded by volume tier, designer margin 25–50 % when studio outsources, retail markup 40–100 % when selling direct, customization premium 10–25 % by level), project settings, and the upstream cost_engine — and produce a structured pricing_buildup JSON.

Order of layers (each step lays a percentage onto the running base — NEVER stack two percentages on the same base):
  1. manufacturing_cost
       + manufacturer_margin          (ALWAYS applied)
       = ex_factory_price
  2. + designer_margin                (ONLY if project.studio_outsources_fabrication == true)
       = trade_price
  3. + retail_markup                  (ONLY if project.selling_direct_to_end_client == true)
       = retail_base
  4. + customization_premium          (ONLY if customization_level != 'none')
       = final_retail_price

Studio voice — short, decisive, no marketing prose.

Hard rules for header:
- currency MUST be 'INR'.
- manufacturing_cost_inr MUST equal project.manufacturing_cost_inr exactly.
- volume_tier MUST equal project.volume_tier and be in volume_tiers_in_scope.
- market_segment MUST equal project.market_segment and be in market_segments_in_scope.
- sales_channel MUST equal project.sales_channel and be in sales_channels_in_scope.
- customization_level MUST equal project.customization_level and be in customization_levels_in_scope.

Hard rules for manufacturer_margin (always present):
- pct_band MUST equal pricing_brd.manufacturer_margin_pct_by_volume[project.volume_tier] verbatim.
- pct MUST sit inside pct_band. Default to band midpoint unless a written reason justifies tighter or looser.
- base_inr MUST equal manufacturing_cost_inr.
- amount_inr = round(base_inr × pct/100, 0).
- ex_factory_price_inr = round(base_inr + amount_inr, 0).

Hard rules for designer_margin:
- applies MUST equal project.studio_outsources_fabrication (true/false).
- If applies == false: pct = 0, amount_inr = 0, base_inr = ex_factory_price_inr, trade_price_inr = ex_factory_price_inr. State 'studio fabricates in-house — designer margin not applicable' in rationale.
- If applies == true: pct_band MUST equal pricing_brd.designer_margin_pct_band ([25, 50]). pct MUST sit inside the band. base_inr = ex_factory_price_inr. amount_inr = round(base_inr × pct/100, 0). trade_price_inr = round(base_inr + amount_inr, 0).

Hard rules for retail_markup:
- applies MUST equal project.selling_direct_to_end_client.
- If applies == false: pct = 0, amount_inr = 0, base_inr = trade_price_inr, retail_base_inr = trade_price_inr. State 'sold via trade channel — retail markup not applicable' in rationale.
- If applies == true: pct_band MUST equal pricing_brd.retail_markup_pct_band ([40, 100]). pct MUST sit inside the band. Pick the lower half (40–60) for mass_market, the upper half (60–100) for luxury, citing market_segment. base_inr = trade_price_inr. amount_inr = round(base_inr × pct/100, 0). retail_base_inr = round(base_inr + amount_inr, 0).

Hard rules for customization_premium:
- pct_band_by_level MUST equal pricing_brd.customization_premium_pct_by_level[project.customization_level] verbatim.
- If customization_level == 'none': pct = 0, amount_inr = 0, base_inr = retail_base_inr, final_retail_price_inr = retail_base_inr. State 'catalogue piece — no customization premium' in rationale.
- Else: pct MUST sit inside pct_band_by_level. base_inr = retail_base_inr. amount_inr = round(base_inr × pct/100, 0). final_retail_price_inr = round(base_inr + amount_inr, 0).

Reconciliation:
- final_retail_price_inr is the LAST step output. Reconcile a verbose price walk in 'reconciliation' showing each layer's running total.
- summary.uplift_pct_over_manufacturing = round((final_retail_price_inr - manufacturing_cost_inr) / manufacturing_cost_inr × 100, 2).
- summary.layers_applied lists exactly the layers that actually moved the price ('manufacturer_margin', 'designer_margin', 'retail_markup', 'customization_premium').

assumptions[] cites every BRD band used and every settings flag (outsourcing, selling channel, customization level, volume tier, market segment).

Never invent BRD percentages. Snap every number to the catalogue."""


# ── JSON schema ─────────────────────────────────────────────────────────────


def _layer_schema(*, with_band: bool = True) -> dict[str, Any]:
    props: dict[str, Any] = {
        "applies": {"type": "boolean"},
        "pct": {"type": "number"},
        "base_inr": {"type": "number"},
        "amount_inr": {"type": "number"},
        "running_total_inr": {"type": "number"},
        "rationale": {"type": "string"},
    }
    required = ["applies", "pct", "base_inr", "amount_inr", "running_total_inr", "rationale"]
    if with_band:
        props["pct_band"] = {
            "type": "array",
            "items": {"type": "number"},
        }
        required.append("pct_band")
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def _customization_layer_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "applies": {"type": "boolean"},
            "level": {"type": "string"},                  # CUSTOMIZATION_LEVELS_IN_SCOPE
            "pct_band_by_level": {
                "type": "array",
                "items": {"type": "number"},              # [low, high]
            },
            "pct": {"type": "number"},
            "base_inr": {"type": "number"},
            "amount_inr": {"type": "number"},
            "running_total_inr": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": [
            "applies", "level", "pct_band_by_level", "pct",
            "base_inr", "amount_inr", "running_total_inr", "rationale",
        ],
        "additionalProperties": False,
    }


PRICING_SCHEMA: dict[str, Any] = {
    "name": "pricing_buildup",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "piece_name": {"type": "string"},
                    "theme": {"type": "string"},
                    "city": {"type": "string"},
                    "currency": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "manufacturing_cost_inr": {"type": "number"},
                    "market_segment": {"type": "string"},
                    "volume_tier": {"type": "string"},
                    "sales_channel": {"type": "string"},
                    "customization_level": {"type": "string"},
                },
                "required": [
                    "project", "piece_name", "theme", "city",
                    "currency", "date_iso", "manufacturing_cost_inr",
                    "market_segment", "volume_tier", "sales_channel",
                    "customization_level",
                ],
                "additionalProperties": False,
            },
            "manufacturer_margin": _layer_schema(),
            "ex_factory_price_inr": {"type": "number"},
            "designer_margin": _layer_schema(),
            "trade_price_inr": {"type": "number"},
            "retail_markup": _layer_schema(),
            "retail_base_inr": {"type": "number"},
            "customization_premium": _customization_layer_schema(),
            "final_retail_price_inr": {"type": "number"},
            "reconciliation": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {"type": "integer"},
                        "label": {"type": "string"},
                        "running_total_inr": {"type": "number"},
                    },
                    "required": ["step", "label", "running_total_inr"],
                    "additionalProperties": False,
                },
            },
            "summary": {
                "type": "object",
                "properties": {
                    "uplift_pct_over_manufacturing": {"type": "number"},
                    "layers_applied": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["uplift_pct_over_manufacturing", "layers_applied"],
                "additionalProperties": False,
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header", "manufacturer_margin", "ex_factory_price_inr",
            "designer_margin", "trade_price_inr",
            "retail_markup", "retail_base_inr",
            "customization_premium", "final_retail_price_inr",
            "reconciliation", "summary", "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: PricingRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Piece: {req.piece_name}\n"
        f"- Manufacturing cost: ₹{req.manufacturing_cost_inr:,.0f}\n"
        f"- Market segment: {req.market_segment}\n"
        f"- Volume tier: {req.volume_tier}\n"
        f"- Sales channel: {req.sales_channel}\n"
        f"- Customization level: {req.customization_level}\n"
        f"- Studio outsources fabrication: {req.studio_outsources_fabrication}\n"
        f"- Selling direct to end-client: {req.selling_direct_to_end_client}\n"
        f"- Date (UTC ISO): {today}\n\n"
        "Produce the pricing_buildup JSON. Walk the price from "
        "manufacturing_cost → ex_factory → trade → retail_base → "
        "final_retail_price. Snap every percentage to the BRD bands; "
        "set non-applicable layers to applies=false / pct=0."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _approx_eq(a: Any, b: Any, tol: float = 1.0) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _within(v: Any, band: list | tuple, *, tol: float = 1e-6) -> bool:
    try:
        lo, hi = float(band[0]), float(band[1])
        return lo - tol <= float(v) <= hi + tol
    except (TypeError, ValueError, IndexError):
        return False


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    project = knowledge.get("project") or {}
    brd = knowledge.get("pricing_brd") or {}
    out: dict[str, list[Any]] = {
        "bad_currency": [],
        "bad_manufacturing_cost": [],
        "bad_volume_tier": [],
        "bad_market_segment": [],
        "bad_sales_channel": [],
        "bad_customization_level": [],

        "bad_manufacturer_band": [],
        "manufacturer_pct_out_of_band": [],
        "bad_manufacturer_base": [],
        "bad_manufacturer_amount": [],
        "bad_ex_factory": [],

        "bad_designer_applies_flag": [],
        "designer_should_zero_when_not_applies": [],
        "bad_designer_band": [],
        "designer_pct_out_of_band": [],
        "bad_designer_base": [],
        "bad_designer_amount": [],
        "bad_trade_price": [],

        "bad_retail_applies_flag": [],
        "retail_should_zero_when_not_applies": [],
        "bad_retail_band": [],
        "retail_pct_out_of_band": [],
        "bad_retail_base": [],
        "bad_retail_amount": [],
        "bad_retail_base_total": [],

        "bad_customization_band": [],
        "customization_pct_out_of_band": [],
        "customization_should_zero_when_none": [],
        "bad_customization_base": [],
        "bad_customization_amount": [],
        "bad_final_retail_price": [],

        "bad_reconciliation": [],
        "bad_uplift_pct": [],
        "bad_layers_applied": [],
    }

    header = spec.get("header") or {}
    if (header.get("currency") or "").upper() != "INR":
        out["bad_currency"].append(header.get("currency"))
    if not _approx_eq(header.get("manufacturing_cost_inr"), project.get("manufacturing_cost_inr"), tol=0.5):
        out["bad_manufacturing_cost"].append({
            "expected": project.get("manufacturing_cost_inr"),
            "actual": header.get("manufacturing_cost_inr"),
        })
    if header.get("volume_tier") != project.get("volume_tier") or header.get("volume_tier") not in VOLUME_TIERS_IN_SCOPE:
        out["bad_volume_tier"].append({
            "expected": project.get("volume_tier"), "actual": header.get("volume_tier"),
        })
    if header.get("market_segment") != project.get("market_segment") or header.get("market_segment") not in MARKET_SEGMENTS_IN_SCOPE:
        out["bad_market_segment"].append({
            "expected": project.get("market_segment"), "actual": header.get("market_segment"),
        })
    if header.get("sales_channel") != project.get("sales_channel") or header.get("sales_channel") not in SALES_CHANNELS_IN_SCOPE:
        out["bad_sales_channel"].append({
            "expected": project.get("sales_channel"), "actual": header.get("sales_channel"),
        })
    if header.get("customization_level") != project.get("customization_level") or header.get("customization_level") not in CUSTOMIZATION_LEVELS_IN_SCOPE:
        out["bad_customization_level"].append({
            "expected": project.get("customization_level"),
            "actual": header.get("customization_level"),
        })

    manufacturing = float(project.get("manufacturing_cost_inr") or 0)

    # ── Manufacturer margin ────────────────────────────────────────────────
    mm = spec.get("manufacturer_margin") or {}
    expected_mm_band = brd.get("manufacturer_margin_pct_by_volume", {}).get(project.get("volume_tier"))
    actual_mm_band = mm.get("pct_band") or []
    if not expected_mm_band or len(actual_mm_band) != 2 or not _approx_eq(actual_mm_band[0], expected_mm_band[0]) or not _approx_eq(actual_mm_band[1], expected_mm_band[1]):
        out["bad_manufacturer_band"].append({
            "expected": list(expected_mm_band or []), "actual": list(actual_mm_band),
        })
    if expected_mm_band and not _within(mm.get("pct"), expected_mm_band):
        out["manufacturer_pct_out_of_band"].append({
            "value": mm.get("pct"), "band": list(expected_mm_band),
        })
    if not _approx_eq(mm.get("base_inr"), manufacturing, tol=1.0):
        out["bad_manufacturer_base"].append({
            "expected": manufacturing, "actual": mm.get("base_inr"),
        })
    expected_mm_amount = round(manufacturing * float(mm.get("pct") or 0) / 100, 0)
    if not _approx_eq(mm.get("amount_inr"), expected_mm_amount, tol=2.0):
        out["bad_manufacturer_amount"].append({
            "expected": expected_mm_amount, "actual": mm.get("amount_inr"),
        })
    expected_ex_factory = round(manufacturing + expected_mm_amount, 0)
    if not _approx_eq(spec.get("ex_factory_price_inr"), expected_ex_factory, tol=2.0):
        out["bad_ex_factory"].append({
            "expected": expected_ex_factory, "actual": spec.get("ex_factory_price_inr"),
        })

    ex_factory = float(spec.get("ex_factory_price_inr") or expected_ex_factory)

    # ── Designer margin ────────────────────────────────────────────────────
    dm = spec.get("designer_margin") or {}
    expected_dm_applies = bool(project.get("studio_outsources_fabrication"))
    if bool(dm.get("applies")) != expected_dm_applies:
        out["bad_designer_applies_flag"].append({
            "expected": expected_dm_applies, "actual": dm.get("applies"),
        })
    expected_dm_band = brd.get("designer_margin_pct_band") or [25, 50]
    if expected_dm_applies:
        actual_dm_band = dm.get("pct_band") or []
        if len(actual_dm_band) != 2 or not _approx_eq(actual_dm_band[0], expected_dm_band[0]) or not _approx_eq(actual_dm_band[1], expected_dm_band[1]):
            out["bad_designer_band"].append({
                "expected": list(expected_dm_band), "actual": list(actual_dm_band),
            })
        if not _within(dm.get("pct"), expected_dm_band):
            out["designer_pct_out_of_band"].append({
                "value": dm.get("pct"), "band": list(expected_dm_band),
            })
        if not _approx_eq(dm.get("base_inr"), ex_factory, tol=2.0):
            out["bad_designer_base"].append({
                "expected": ex_factory, "actual": dm.get("base_inr"),
            })
        expected_dm_amount = round(ex_factory * float(dm.get("pct") or 0) / 100, 0)
        if not _approx_eq(dm.get("amount_inr"), expected_dm_amount, tol=2.0):
            out["bad_designer_amount"].append({
                "expected": expected_dm_amount, "actual": dm.get("amount_inr"),
            })
        expected_trade = round(ex_factory + expected_dm_amount, 0)
    else:
        if (dm.get("pct") or 0) != 0 or (dm.get("amount_inr") or 0) != 0:
            out["designer_should_zero_when_not_applies"].append({
                "pct": dm.get("pct"), "amount": dm.get("amount_inr"),
            })
        expected_trade = round(ex_factory, 0)

    if not _approx_eq(spec.get("trade_price_inr"), expected_trade, tol=2.0):
        out["bad_trade_price"].append({
            "expected": expected_trade, "actual": spec.get("trade_price_inr"),
        })
    trade_price = float(spec.get("trade_price_inr") or expected_trade)

    # ── Retail markup ──────────────────────────────────────────────────────
    rm = spec.get("retail_markup") or {}
    expected_rm_applies = bool(project.get("selling_direct_to_end_client"))
    if bool(rm.get("applies")) != expected_rm_applies:
        out["bad_retail_applies_flag"].append({
            "expected": expected_rm_applies, "actual": rm.get("applies"),
        })
    expected_rm_band = brd.get("retail_markup_pct_band") or [40, 100]
    if expected_rm_applies:
        actual_rm_band = rm.get("pct_band") or []
        if len(actual_rm_band) != 2 or not _approx_eq(actual_rm_band[0], expected_rm_band[0]) or not _approx_eq(actual_rm_band[1], expected_rm_band[1]):
            out["bad_retail_band"].append({
                "expected": list(expected_rm_band), "actual": list(actual_rm_band),
            })
        if not _within(rm.get("pct"), expected_rm_band):
            out["retail_pct_out_of_band"].append({
                "value": rm.get("pct"), "band": list(expected_rm_band),
            })
        if not _approx_eq(rm.get("base_inr"), trade_price, tol=2.0):
            out["bad_retail_base"].append({
                "expected": trade_price, "actual": rm.get("base_inr"),
            })
        expected_rm_amount = round(trade_price * float(rm.get("pct") or 0) / 100, 0)
        if not _approx_eq(rm.get("amount_inr"), expected_rm_amount, tol=2.0):
            out["bad_retail_amount"].append({
                "expected": expected_rm_amount, "actual": rm.get("amount_inr"),
            })
        expected_retail_base = round(trade_price + expected_rm_amount, 0)
    else:
        if (rm.get("pct") or 0) != 0 or (rm.get("amount_inr") or 0) != 0:
            out["retail_should_zero_when_not_applies"].append({
                "pct": rm.get("pct"), "amount": rm.get("amount_inr"),
            })
        expected_retail_base = round(trade_price, 0)

    if not _approx_eq(spec.get("retail_base_inr"), expected_retail_base, tol=2.0):
        out["bad_retail_base_total"].append({
            "expected": expected_retail_base, "actual": spec.get("retail_base_inr"),
        })
    retail_base = float(spec.get("retail_base_inr") or expected_retail_base)

    # ── Customization premium ──────────────────────────────────────────────
    cp = spec.get("customization_premium") or {}
    level = (project.get("customization_level") or "none").lower()
    expected_cp_band = brd.get("customization_premium_pct_by_level", {}).get(level)
    if expected_cp_band is None:
        out["bad_customization_level"].append({"level": level, "reason": "not in BRD table"})
        expected_cp_band = [0, 0]
    actual_cp_band = cp.get("pct_band_by_level") or []
    if len(actual_cp_band) != 2 or not _approx_eq(actual_cp_band[0], expected_cp_band[0]) or not _approx_eq(actual_cp_band[1], expected_cp_band[1]):
        out["bad_customization_band"].append({
            "expected": list(expected_cp_band), "actual": list(actual_cp_band),
        })

    if level == "none":
        if (cp.get("pct") or 0) != 0 or (cp.get("amount_inr") or 0) != 0:
            out["customization_should_zero_when_none"].append({
                "pct": cp.get("pct"), "amount": cp.get("amount_inr"),
            })
        expected_final = round(retail_base, 0)
    else:
        if not _within(cp.get("pct"), expected_cp_band):
            out["customization_pct_out_of_band"].append({
                "level": level, "value": cp.get("pct"), "band": list(expected_cp_band),
            })
        if not _approx_eq(cp.get("base_inr"), retail_base, tol=2.0):
            out["bad_customization_base"].append({
                "expected": retail_base, "actual": cp.get("base_inr"),
            })
        expected_cp_amount = round(retail_base * float(cp.get("pct") or 0) / 100, 0)
        if not _approx_eq(cp.get("amount_inr"), expected_cp_amount, tol=2.0):
            out["bad_customization_amount"].append({
                "expected": expected_cp_amount, "actual": cp.get("amount_inr"),
            })
        expected_final = round(retail_base + expected_cp_amount, 0)

    if not _approx_eq(spec.get("final_retail_price_inr"), expected_final, tol=2.0):
        out["bad_final_retail_price"].append({
            "expected": expected_final, "actual": spec.get("final_retail_price_inr"),
        })

    final_price = float(spec.get("final_retail_price_inr") or expected_final)

    # ── Summary ────────────────────────────────────────────────────────────
    summary = spec.get("summary") or {}
    if manufacturing > 0:
        expected_uplift = round((final_price - manufacturing) / manufacturing * 100, 2)
        if not _approx_eq(summary.get("uplift_pct_over_manufacturing"), expected_uplift, tol=0.05):
            out["bad_uplift_pct"].append({
                "expected": expected_uplift,
                "actual": summary.get("uplift_pct_over_manufacturing"),
            })

    expected_layers = ["manufacturer_margin"]
    if expected_dm_applies:
        expected_layers.append("designer_margin")
    if expected_rm_applies:
        expected_layers.append("retail_markup")
    if level != "none":
        expected_layers.append("customization_premium")
    actual_layers = summary.get("layers_applied") or []
    if list(actual_layers) != expected_layers:
        out["bad_layers_applied"].append({
            "expected": expected_layers, "actual": list(actual_layers),
        })

    # ── Reconciliation ─────────────────────────────────────────────────────
    recon = spec.get("reconciliation") or []
    if recon:
        last = recon[-1]
        if not _approx_eq(last.get("running_total_inr"), final_price, tol=2.0):
            out["bad_reconciliation"].append({
                "expected_last": final_price,
                "actual_last": last.get("running_total_inr"),
            })

    return {
        "currency_is_inr": not out["bad_currency"],
        "bad_currency": out["bad_currency"],
        "manufacturing_cost_matches": not out["bad_manufacturing_cost"],
        "bad_manufacturing_cost": out["bad_manufacturing_cost"],
        "volume_tier_in_scope": not out["bad_volume_tier"],
        "bad_volume_tier": out["bad_volume_tier"],
        "market_segment_in_scope": not out["bad_market_segment"],
        "bad_market_segment": out["bad_market_segment"],
        "sales_channel_in_scope": not out["bad_sales_channel"],
        "bad_sales_channel": out["bad_sales_channel"],
        "customization_level_in_scope": not out["bad_customization_level"],
        "bad_customization_level": out["bad_customization_level"],

        "manufacturer_band_matches_brd": not out["bad_manufacturer_band"],
        "bad_manufacturer_band": out["bad_manufacturer_band"],
        "manufacturer_pct_in_band": not out["manufacturer_pct_out_of_band"],
        "manufacturer_pct_out_of_band": out["manufacturer_pct_out_of_band"],
        "manufacturer_base_is_manufacturing_cost": not out["bad_manufacturer_base"],
        "bad_manufacturer_base": out["bad_manufacturer_base"],
        "manufacturer_amount_consistent": not out["bad_manufacturer_amount"],
        "bad_manufacturer_amount": out["bad_manufacturer_amount"],
        "ex_factory_price_consistent": not out["bad_ex_factory"],
        "bad_ex_factory": out["bad_ex_factory"],

        "designer_applies_flag_correct": not out["bad_designer_applies_flag"],
        "bad_designer_applies_flag": out["bad_designer_applies_flag"],
        "designer_band_matches_brd": not out["bad_designer_band"],
        "bad_designer_band": out["bad_designer_band"],
        "designer_pct_in_band": not out["designer_pct_out_of_band"],
        "designer_pct_out_of_band": out["designer_pct_out_of_band"],
        "designer_base_is_ex_factory": not out["bad_designer_base"],
        "bad_designer_base": out["bad_designer_base"],
        "designer_amount_consistent": not out["bad_designer_amount"],
        "bad_designer_amount": out["bad_designer_amount"],
        "designer_zero_when_not_applies": not out["designer_should_zero_when_not_applies"],
        "designer_should_zero_when_not_applies": out["designer_should_zero_when_not_applies"],
        "trade_price_consistent": not out["bad_trade_price"],
        "bad_trade_price": out["bad_trade_price"],

        "retail_applies_flag_correct": not out["bad_retail_applies_flag"],
        "bad_retail_applies_flag": out["bad_retail_applies_flag"],
        "retail_band_matches_brd": not out["bad_retail_band"],
        "bad_retail_band": out["bad_retail_band"],
        "retail_pct_in_band": not out["retail_pct_out_of_band"],
        "retail_pct_out_of_band": out["retail_pct_out_of_band"],
        "retail_base_is_trade_price": not out["bad_retail_base"],
        "bad_retail_base": out["bad_retail_base"],
        "retail_amount_consistent": not out["bad_retail_amount"],
        "bad_retail_amount": out["bad_retail_amount"],
        "retail_zero_when_not_applies": not out["retail_should_zero_when_not_applies"],
        "retail_should_zero_when_not_applies": out["retail_should_zero_when_not_applies"],
        "retail_base_total_consistent": not out["bad_retail_base_total"],
        "bad_retail_base_total": out["bad_retail_base_total"],

        "customization_band_matches_brd": not out["bad_customization_band"],
        "bad_customization_band": out["bad_customization_band"],
        "customization_pct_in_band": not out["customization_pct_out_of_band"],
        "customization_pct_out_of_band": out["customization_pct_out_of_band"],
        "customization_zero_when_none": not out["customization_should_zero_when_none"],
        "customization_should_zero_when_none": out["customization_should_zero_when_none"],
        "customization_base_is_retail_base": not out["bad_customization_base"],
        "bad_customization_base": out["bad_customization_base"],
        "customization_amount_consistent": not out["bad_customization_amount"],
        "bad_customization_amount": out["bad_customization_amount"],
        "final_retail_price_consistent": not out["bad_final_retail_price"],
        "bad_final_retail_price": out["bad_final_retail_price"],

        "reconciliation_lands_at_final_price": not out["bad_reconciliation"],
        "bad_reconciliation": out["bad_reconciliation"],
        "uplift_pct_consistent": not out["bad_uplift_pct"],
        "bad_uplift_pct": out["bad_uplift_pct"],
        "layers_applied_match_settings": not out["bad_layers_applied"],
        "bad_layers_applied": out["bad_layers_applied"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class PricingError(RuntimeError):
    """Raised when the LLM pricing stage cannot produce a grounded sheet."""


async def generate_pricing_buildup(req: PricingRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise PricingError(
            "OpenAI API key is not configured. The pricing stage requires "
            "a live LLM call; no static fallback is served."
        )
    if req.volume_tier.lower() not in VOLUME_TIERS_IN_SCOPE:
        raise PricingError(
            f"Unknown volume_tier '{req.volume_tier}'. "
            f"Pick one of: {', '.join(VOLUME_TIERS_IN_SCOPE)}."
        )
    if req.customization_level.lower() not in CUSTOMIZATION_LEVELS_IN_SCOPE:
        raise PricingError(
            f"Unknown customization_level '{req.customization_level}'. "
            f"Pick one of: {', '.join(CUSTOMIZATION_LEVELS_IN_SCOPE)}."
        )
    if req.market_segment.lower() not in MARKET_SEGMENTS_IN_SCOPE:
        raise PricingError(
            f"Unknown market_segment '{req.market_segment}'. "
            f"Pick one of: {', '.join(MARKET_SEGMENTS_IN_SCOPE)}."
        )
    if req.sales_channel.lower() not in SALES_CHANNELS_IN_SCOPE:
        raise PricingError(
            f"Unknown sales_channel '{req.sales_channel}'. "
            f"Pick one of: {', '.join(SALES_CHANNELS_IN_SCOPE)}."
        )

    knowledge = build_pricing_knowledge(req)
    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": PRICING_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": PRICING_SCHEMA,
            },
            temperature=0.2,
            max_tokens=1800,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for pricing buildup")
        raise PricingError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PricingError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    return {
        "id": "pricing_buildup",
        "name": "Markup & Pricing Buildup",
        "model": settings.openai_model,
        "knowledge": knowledge,
        "pricing_buildup": spec,
        "validation": validation,
    }
