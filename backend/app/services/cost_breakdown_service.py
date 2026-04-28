"""LLM-driven Cost Breakdown Report (BRD Layer 4C).

The client-facing summary that rolls up Layer 4A (parametric cost
engine) and Layer 4B (markup & pricing) into one defendable sheet:

    ├── Material cost: ₹X, Y % of total
    ├── Labor cost:    ₹X, Y % of total
    ├── Overhead:      ₹X, Y % of total
    ├── Margin:        ₹X, Y % of total
    └── Retail price:  ₹X

Pipeline contract — same as every other LLM service:

    INPUT (cost_engine + pricing_buildup objects from 4A / 4B)
      → INJECT  (BRD definitions of every line + the upstream specs
                 verbatim so the LLM can cite numbers, not invent them)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (every ₹ matches the upstream specs exactly; every
                   % matches component / final_retail × 100; the four
                   lines + retail price reconcile end-to-end)
      → OUTPUT  (cost_breakdown JSON conforming to the BRD template)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import costing

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


# ── Request schema ──────────────────────────────────────────────────────────


class CostBreakdownRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    piece_name: str = Field(default="Primary piece", max_length=160)
    theme: str = Field(default="", max_length=64)
    city: str = Field(default="", max_length=80)
    cost_engine: dict[str, Any] = Field(
        ..., description="The 4A cost_engine spec object (header + material_cost + labor_cost + overhead + total_manufacturing_cost_inr).",
    )
    pricing_buildup: dict[str, Any] = Field(
        ..., description="The 4B pricing_buildup spec object (manufacturer_margin + designer_margin + retail_markup + customization_premium + final_retail_price_inr).",
    )


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _extract_components(req: CostBreakdownRequest) -> dict[str, float]:
    """Pull canonical line ₹ from upstream specs."""
    ce = req.cost_engine or {}
    pb = req.pricing_buildup or {}
    material = float((ce.get("material_cost") or {}).get("material_subtotal_inr") or 0)
    labor = float((ce.get("labor_cost") or {}).get("labor_subtotal_inr") or 0)
    overhead = float((ce.get("overhead") or {}).get("overhead_subtotal_inr") or 0)
    manufacturing = float(ce.get("total_manufacturing_cost_inr") or (material + labor + overhead))
    final_retail = float(pb.get("final_retail_price_inr") or 0)
    margin_total = round(final_retail - manufacturing, 0)

    layers = []
    for key, label in (
        ("manufacturer_margin", "Manufacturer margin"),
        ("designer_margin", "Designer margin"),
        ("retail_markup", "Retail markup"),
        ("customization_premium", "Customization premium"),
    ):
        layer = pb.get(key) or {}
        applies = layer.get("applies")
        amt = float(layer.get("amount_inr") or 0)
        layers.append({
            "key": key,
            "label": label,
            "applies": bool(applies),
            "pct": float(layer.get("pct") or 0),
            "amount_inr": round(amt, 0),
        })

    return {
        "material_inr": round(material, 0),
        "labor_inr": round(labor, 0),
        "overhead_inr": round(overhead, 0),
        "manufacturing_cost_inr": round(manufacturing, 0),
        "margin_total_inr": margin_total,
        "final_retail_price_inr": round(final_retail, 0),
        "margin_layers": layers,
    }


def build_cost_breakdown_knowledge(req: CostBreakdownRequest) -> dict[str, Any]:
    components = _extract_components(req)
    return {
        "project": {
            "name": req.project_name,
            "piece_name": req.piece_name,
            "theme": req.theme or None,
            "city": req.city or None,
        },
        "components": components,
        "upstream": {
            "cost_engine": req.cost_engine,
            "pricing_buildup": req.pricing_buildup,
        },
        "brd_definitions": {
            "material_cost": (
                "Material subtotal from 4A — "
                "Σ(line subtotal_with_waste) + Σ(finish) + Σ(hardware)."
            ),
            "labor_cost": (
                "Labor subtotal from 4A — "
                "Σ(hours × effective_rate × city_index) per trade."
            ),
            "overhead": (
                "Overhead subtotal from 4A — "
                "workshop_allocation (30–40 % of direct) + quality_control "
                "(5–10 % of labor) + packaging_shipping (10–15 % of "
                "product cost)."
            ),
            "margin": (
                "All BRD 4B layers that moved the price — "
                "manufacturer_margin (30–60 % by volume) + designer_margin "
                "(25–50 % when outsourcing) + retail_markup (40–100 % when "
                "selling direct) + customization_premium (10–25 % by level). "
                "= final_retail_price − total_manufacturing_cost."
            ),
            "retail_price": (
                "Final retail price from 4B — what the end client pays."
            ),
        },
        "brd_constants": {
            "waste_factor_pct": list(costing.WASTE_FACTOR_PCT),
            "finish_cost_pct_of_material": list(costing.FINISH_COST_PCT_OF_MATERIAL),
            "workshop_overhead_pct_of_direct": list(costing.WORKSHOP_OVERHEAD_PCT_OF_DIRECT),
            "qc_pct_of_labor": list(costing.QC_PCT_OF_LABOR),
            "packaging_logistics_pct_of_product": list(costing.PACKAGING_LOGISTICS_PCT_OF_PRODUCT),
            "manufacturer_margin_pct_by_volume": {
                k: list(v) for k, v in costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.items()
            },
            "designer_margin_pct_band": list(costing.DESIGNER_MARGIN_PCT),
            "retail_markup_pct_band": list(costing.RETAIL_MARKUP_PCT),
            "customization_premium_pct_by_level": {
                k: list(v) for k, v in costing.CUSTOMIZATION_PREMIUM_PCT_BY_LEVEL.items()
            },
        },
    }


# ── System prompt ───────────────────────────────────────────────────────────


COST_BREAKDOWN_SYSTEM_PROMPT = """You are a senior studio principal authoring the *Cost Breakdown Report* (BRD Layer 4C) — the one-page summary the client receives alongside the quote.

Read the [KNOWLEDGE] block — components (material, labor, overhead, manufacturing_cost, margin_total, final_retail_price), the upstream cost_engine and pricing_buildup specs, BRD line definitions and constants — and produce a structured cost_breakdown JSON.

The report has exactly five rows:
    Material cost  | Labor cost  | Overhead  | Margin  | Retail price

Studio voice — short, decisive, no marketing prose. Numbers come from the upstream specs; the LLM's job is to lay out the report and write defendable one-line rationales for each row, NOT to invent numbers.

Hard rules for header:
- currency MUST be 'INR'.
- final_retail_price_inr MUST equal components.final_retail_price_inr.
- manufacturing_cost_inr MUST equal components.manufacturing_cost_inr.

Hard rules for line items (one entry per row, in the order: material, labor, overhead, margin):
- amount_inr MUST equal the corresponding components value verbatim:
    material → components.material_inr
    labor    → components.labor_inr
    overhead → components.overhead_inr
    margin   → components.margin_total_inr
- pct_of_retail = round(amount_inr / components.final_retail_price_inr × 100, 2). Snap to 2 decimals.
- pct_of_manufacturing = round(amount_inr / components.manufacturing_cost_inr × 100, 2) for material/labor/overhead. For the margin row, set pct_of_manufacturing = 0 (it sits above manufacturing cost) and state it in rationale.
- rationale (one short sentence) cites the BRD definition from brd_definitions and any noteworthy band (e.g. "workshop overhead at the BRD-mid 35 % drives this", "manufacturer margin small_batch band 40–55 %").

Hard rule for the margin row:
- breakdown[] decomposes margin_total_inr into the 4B layers that actually moved the price. Each entry's amount_inr MUST equal upstream.pricing_buildup.<layer>.amount_inr. Layers with applies=false MUST be omitted.
- Σ breakdown[].amount_inr MUST equal margin_total_inr (snap to 0 tolerance).

Hard rules for retail_price row:
- amount_inr MUST equal components.final_retail_price_inr.
- pct_of_retail MUST equal 100 exactly.
- rationale states it as the FINAL number the client pays.

Reconciliation:
- reconciliation.sum_of_lines_inr = material + labor + overhead + margin (re-derive).
- reconciliation.matches_retail_price MUST be true (sum == final_retail_price within ±2 INR rounding).
- reconciliation.note explains the formula in plain English.

assumptions[] cites every band invoked and any rounding choice.

Never override the upstream numbers. Snap percentages to 2 decimals."""


# ── JSON schema ─────────────────────────────────────────────────────────────


def _row_schema(*, with_pct_of_mfg: bool = True) -> dict[str, Any]:
    props: dict[str, Any] = {
        "label": {"type": "string"},
        "amount_inr": {"type": "number"},
        "pct_of_retail": {"type": "number"},
        "rationale": {"type": "string"},
    }
    required = ["label", "amount_inr", "pct_of_retail", "rationale"]
    if with_pct_of_mfg:
        props["pct_of_manufacturing"] = {"type": "number"}
        required.append("pct_of_manufacturing")
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def _margin_row_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "amount_inr": {"type": "number"},
            "pct_of_retail": {"type": "number"},
            "pct_of_manufacturing": {"type": "number"},
            "breakdown": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "layer": {"type": "string"},        # manufacturer_margin / designer_margin / ...
                        "amount_inr": {"type": "number"},
                        "pct": {"type": "number"},
                        "rationale": {"type": "string"},
                    },
                    "required": ["layer", "amount_inr", "pct", "rationale"],
                    "additionalProperties": False,
                },
            },
            "rationale": {"type": "string"},
        },
        "required": [
            "label", "amount_inr", "pct_of_retail",
            "pct_of_manufacturing", "breakdown", "rationale",
        ],
        "additionalProperties": False,
    }


COST_BREAKDOWN_SCHEMA: dict[str, Any] = {
    "name": "cost_breakdown",
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
                    "final_retail_price_inr": {"type": "number"},
                },
                "required": [
                    "project", "piece_name", "theme", "city",
                    "currency", "date_iso",
                    "manufacturing_cost_inr", "final_retail_price_inr",
                ],
                "additionalProperties": False,
            },
            "material_cost": _row_schema(),
            "labor_cost": _row_schema(),
            "overhead": _row_schema(),
            "margin": _margin_row_schema(),
            "retail_price": _row_schema(with_pct_of_mfg=False),
            "reconciliation": {
                "type": "object",
                "properties": {
                    "sum_of_lines_inr": {"type": "number"},
                    "matches_retail_price": {"type": "boolean"},
                    "note": {"type": "string"},
                },
                "required": ["sum_of_lines_inr", "matches_retail_price", "note"],
                "additionalProperties": False,
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header", "material_cost", "labor_cost", "overhead",
            "margin", "retail_price", "reconciliation", "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: CostBreakdownRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    components = knowledge["components"]
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Piece: {req.piece_name}\n"
        f"- City: {req.city or '(not specified)'}\n"
        f"- Manufacturing cost: ₹{components['manufacturing_cost_inr']:,.0f}\n"
        f"- Final retail price: ₹{components['final_retail_price_inr']:,.0f}\n"
        f"- Margin total: ₹{components['margin_total_inr']:,.0f}\n"
        f"- Date (UTC ISO): {today}\n\n"
        "Produce the cost_breakdown JSON. Five rows in order: material_cost, "
        "labor_cost, overhead, margin (with per-layer breakdown), retail_price. "
        "Cite ₹ verbatim from components; compute % of retail to two "
        "decimals. Reconciliation MUST land on final_retail_price."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _approx_eq(a: Any, b: Any, tol: float = 1.0) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    components = knowledge.get("components") or {}
    upstream = knowledge.get("upstream") or {}
    pb = upstream.get("pricing_buildup") or {}

    out: dict[str, list[Any]] = {
        "bad_currency": [],
        "bad_manufacturing_cost": [],
        "bad_final_retail_price": [],
        "bad_material_amount": [],
        "bad_material_pct_of_retail": [],
        "bad_material_pct_of_mfg": [],
        "bad_labor_amount": [],
        "bad_labor_pct_of_retail": [],
        "bad_labor_pct_of_mfg": [],
        "bad_overhead_amount": [],
        "bad_overhead_pct_of_retail": [],
        "bad_overhead_pct_of_mfg": [],
        "bad_margin_amount": [],
        "bad_margin_pct_of_retail": [],
        "bad_margin_breakdown_amount": [],
        "bad_margin_breakdown_sum": [],
        "margin_breakdown_includes_inactive_layer": [],
        "margin_breakdown_missing_active_layer": [],
        "bad_retail_amount": [],
        "bad_retail_pct_of_retail": [],
        "bad_reconciliation_sum": [],
        "reconciliation_does_not_match": [],
    }

    header = spec.get("header") or {}
    if (header.get("currency") or "").upper() != "INR":
        out["bad_currency"].append(header.get("currency"))
    if not _approx_eq(header.get("manufacturing_cost_inr"), components.get("manufacturing_cost_inr"), tol=1.0):
        out["bad_manufacturing_cost"].append({
            "expected": components.get("manufacturing_cost_inr"),
            "actual": header.get("manufacturing_cost_inr"),
        })
    if not _approx_eq(header.get("final_retail_price_inr"), components.get("final_retail_price_inr"), tol=1.0):
        out["bad_final_retail_price"].append({
            "expected": components.get("final_retail_price_inr"),
            "actual": header.get("final_retail_price_inr"),
        })

    final_retail = float(components.get("final_retail_price_inr") or 0)
    manufacturing = float(components.get("manufacturing_cost_inr") or 0)

    def _check_row(row_key: str, expected_amount: float, *, pct_of_mfg_zero: bool = False) -> None:
        row = spec.get(row_key) or {}
        if not _approx_eq(row.get("amount_inr"), expected_amount, tol=1.0):
            out[f"bad_{row_key}_amount"].append({
                "expected": expected_amount, "actual": row.get("amount_inr"),
            })
        if final_retail > 0:
            expected_pct_retail = round(expected_amount / final_retail * 100, 2)
            if not _approx_eq(row.get("pct_of_retail"), expected_pct_retail, tol=0.05):
                out[f"bad_{row_key}_pct_of_retail"].append({
                    "expected": expected_pct_retail, "actual": row.get("pct_of_retail"),
                })
        if pct_of_mfg_zero:
            return
        if manufacturing > 0:
            expected_pct_mfg = round(expected_amount / manufacturing * 100, 2)
            if not _approx_eq(row.get("pct_of_manufacturing"), expected_pct_mfg, tol=0.05):
                out[f"bad_{row_key}_pct_of_mfg"].append({
                    "expected": expected_pct_mfg, "actual": row.get("pct_of_manufacturing"),
                })

    _check_row("material_cost", float(components.get("material_inr") or 0))
    _check_row("labor_cost", float(components.get("labor_inr") or 0))
    _check_row("overhead", float(components.get("overhead_inr") or 0))

    # Margin row.
    margin_row = spec.get("margin") or {}
    expected_margin = float(components.get("margin_total_inr") or 0)
    if not _approx_eq(margin_row.get("amount_inr"), expected_margin, tol=1.0):
        out["bad_margin_amount"].append({
            "expected": expected_margin, "actual": margin_row.get("amount_inr"),
        })
    if final_retail > 0:
        expected_pct_retail = round(expected_margin / final_retail * 100, 2)
        if not _approx_eq(margin_row.get("pct_of_retail"), expected_pct_retail, tol=0.05):
            out["bad_margin_pct_of_retail"].append({
                "expected": expected_pct_retail, "actual": margin_row.get("pct_of_retail"),
            })

    breakdown = margin_row.get("breakdown") or []
    seen_layers = {b.get("layer"): b for b in breakdown}
    for layer_key in (
        "manufacturer_margin", "designer_margin",
        "retail_markup", "customization_premium",
    ):
        layer = pb.get(layer_key) or {}
        applies = bool(layer.get("applies"))
        is_in_breakdown = layer_key in seen_layers
        if applies and not is_in_breakdown:
            out["margin_breakdown_missing_active_layer"].append(layer_key)
        if not applies and is_in_breakdown:
            out["margin_breakdown_includes_inactive_layer"].append(layer_key)
        if applies and is_in_breakdown:
            expected_layer_amt = float(layer.get("amount_inr") or 0)
            actual_layer_amt = float(seen_layers[layer_key].get("amount_inr") or 0)
            if not _approx_eq(actual_layer_amt, expected_layer_amt, tol=1.0):
                out["bad_margin_breakdown_amount"].append({
                    "layer": layer_key,
                    "expected": expected_layer_amt, "actual": actual_layer_amt,
                })

    sum_breakdown = sum(float(b.get("amount_inr") or 0) for b in breakdown)
    if not _approx_eq(sum_breakdown, expected_margin, tol=2.0):
        out["bad_margin_breakdown_sum"].append({
            "expected": expected_margin, "actual": round(sum_breakdown, 0),
        })

    # Retail price row.
    retail_row = spec.get("retail_price") or {}
    if not _approx_eq(retail_row.get("amount_inr"), final_retail, tol=1.0):
        out["bad_retail_amount"].append({
            "expected": final_retail, "actual": retail_row.get("amount_inr"),
        })
    if not _approx_eq(retail_row.get("pct_of_retail"), 100, tol=0.05):
        out["bad_retail_pct_of_retail"].append({
            "expected": 100, "actual": retail_row.get("pct_of_retail"),
        })

    # Reconciliation.
    recon = spec.get("reconciliation") or {}
    expected_sum = (
        float(components.get("material_inr") or 0)
        + float(components.get("labor_inr") or 0)
        + float(components.get("overhead_inr") or 0)
        + expected_margin
    )
    if not _approx_eq(recon.get("sum_of_lines_inr"), expected_sum, tol=2.0):
        out["bad_reconciliation_sum"].append({
            "expected": round(expected_sum, 0), "actual": recon.get("sum_of_lines_inr"),
        })
    matches = bool(recon.get("matches_retail_price"))
    if matches != _approx_eq(expected_sum, final_retail, tol=2.0):
        out["reconciliation_does_not_match"].append({
            "expected_sum": round(expected_sum, 0),
            "final_retail_price_inr": final_retail,
            "claimed_match": matches,
        })

    return {
        "currency_is_inr": not out["bad_currency"],
        "bad_currency": out["bad_currency"],
        "manufacturing_cost_matches_upstream": not out["bad_manufacturing_cost"],
        "bad_manufacturing_cost": out["bad_manufacturing_cost"],
        "final_retail_price_matches_upstream": not out["bad_final_retail_price"],
        "bad_final_retail_price": out["bad_final_retail_price"],
        "material_amount_matches_4a": not out["bad_material_amount"],
        "bad_material_amount": out["bad_material_amount"],
        "material_pct_of_retail_consistent": not out["bad_material_pct_of_retail"],
        "bad_material_pct_of_retail": out["bad_material_pct_of_retail"],
        "material_pct_of_mfg_consistent": not out["bad_material_pct_of_mfg"],
        "bad_material_pct_of_mfg": out["bad_material_pct_of_mfg"],
        "labor_amount_matches_4a": not out["bad_labor_amount"],
        "bad_labor_amount": out["bad_labor_amount"],
        "labor_pct_of_retail_consistent": not out["bad_labor_pct_of_retail"],
        "bad_labor_pct_of_retail": out["bad_labor_pct_of_retail"],
        "labor_pct_of_mfg_consistent": not out["bad_labor_pct_of_mfg"],
        "bad_labor_pct_of_mfg": out["bad_labor_pct_of_mfg"],
        "overhead_amount_matches_4a": not out["bad_overhead_amount"],
        "bad_overhead_amount": out["bad_overhead_amount"],
        "overhead_pct_of_retail_consistent": not out["bad_overhead_pct_of_retail"],
        "bad_overhead_pct_of_retail": out["bad_overhead_pct_of_retail"],
        "overhead_pct_of_mfg_consistent": not out["bad_overhead_pct_of_mfg"],
        "bad_overhead_pct_of_mfg": out["bad_overhead_pct_of_mfg"],
        "margin_amount_matches_retail_minus_mfg": not out["bad_margin_amount"],
        "bad_margin_amount": out["bad_margin_amount"],
        "margin_pct_of_retail_consistent": not out["bad_margin_pct_of_retail"],
        "bad_margin_pct_of_retail": out["bad_margin_pct_of_retail"],
        "margin_breakdown_amounts_match_4b": not out["bad_margin_breakdown_amount"],
        "bad_margin_breakdown_amount": out["bad_margin_breakdown_amount"],
        "margin_breakdown_sums_to_total": not out["bad_margin_breakdown_sum"],
        "bad_margin_breakdown_sum": out["bad_margin_breakdown_sum"],
        "no_inactive_layers_in_breakdown": not out["margin_breakdown_includes_inactive_layer"],
        "margin_breakdown_includes_inactive_layer": out["margin_breakdown_includes_inactive_layer"],
        "all_active_layers_in_breakdown": not out["margin_breakdown_missing_active_layer"],
        "margin_breakdown_missing_active_layer": out["margin_breakdown_missing_active_layer"],
        "retail_amount_matches_final": not out["bad_retail_amount"],
        "bad_retail_amount": out["bad_retail_amount"],
        "retail_pct_is_100": not out["bad_retail_pct_of_retail"],
        "bad_retail_pct_of_retail": out["bad_retail_pct_of_retail"],
        "reconciliation_sum_consistent": not out["bad_reconciliation_sum"],
        "bad_reconciliation_sum": out["bad_reconciliation_sum"],
        "reconciliation_match_flag_correct": not out["reconciliation_does_not_match"],
        "reconciliation_does_not_match": out["reconciliation_does_not_match"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class CostBreakdownError(RuntimeError):
    """Raised when the LLM cost breakdown stage cannot produce a grounded sheet."""


async def generate_cost_breakdown(req: CostBreakdownRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise CostBreakdownError(
            "OpenAI API key is not configured. The cost breakdown stage requires "
            "a live LLM call; no static fallback is served."
        )

    # Hard-fail when upstream specs are missing the totals we need.
    components = _extract_components(req)
    if components["final_retail_price_inr"] <= 0:
        raise CostBreakdownError(
            "pricing_buildup.final_retail_price_inr is missing or zero — "
            "cannot compute cost breakdown."
        )
    if components["manufacturing_cost_inr"] <= 0:
        raise CostBreakdownError(
            "cost_engine.total_manufacturing_cost_inr is missing or zero — "
            "cannot compute cost breakdown."
        )

    knowledge = build_cost_breakdown_knowledge(req)
    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": COST_BREAKDOWN_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": COST_BREAKDOWN_SCHEMA,
            },
            temperature=0.15,
            max_tokens=1600,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for cost breakdown")
        raise CostBreakdownError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CostBreakdownError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    return {
        "id": "cost_breakdown",
        "name": "Cost Breakdown Report",
        "model": settings.openai_model,
        "knowledge": knowledge,
        "cost_breakdown": spec,
        "validation": validation,
    }
