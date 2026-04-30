"""LLM-driven Parametric Cost Engine (BRD Layer 4A).

Authors a real practice-grade *cost engine* breakdown — the document
the studio PM hands to the client to defend the price quote and the
fabricator hands the workshop manager to plan resourcing.

Pipeline contract — same as every other LLM service in the project:

    INPUT (theme + parametric_spec + optional material/manufacturing
           specs + city + market segment + hardware count)
      → INJECT  (BRD cost constants — material rates per kg/m², waste
                 10–15 %, finish 15–25 %, hardware ₹500–2 000/piece,
                 labor rates per trade, workshop overhead 30–40 %, QC
                 5–10 % of labor, packaging 10–15 % of product cost)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (every line item snapped to BRD bands; subtotals
                   recomputed from line items; overhead applied as a
                   percentage of the right base; total manufacturing
                   cost = material + labor + overhead)
      → OUTPUT  (cost_engine JSON conforming to the BRD template)

This is the LAYER-4A document — i.e. the COST ENGINE up to TOTAL
MANUFACTURING COST. Margin / packaging-to-retail is layered later in
4B. The engine prices a single piece (or a single room's worth of
millwork) — multi-piece projects call this once per piece.

Stage 1 (April 2026) — knowledge externalisation
------------------------------------------------
``build_cost_engine_knowledge`` and ``generate_cost_engine`` now:

- Read every cost constant from versioned DB rows
  (``app.repositories.pricing``) instead of hardcoded literals.
- Record an immutable :class:`PricingSnapshot` per run so the
  numbers reproduce forever, even after admin price updates.
- Optionally **replay** a prior snapshot via ``snapshot_id`` for
  re-fetching old estimates without drift.

Both functions now require an ``AsyncSession`` (FastAPI dependency);
callers update the route signature accordingly.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.knowledge import manufacturing
from app.services.pricing import (
    build_pricing_knowledge,
    load_snapshot,
    record_snapshot,
)
from app.services.themes import get_theme

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
# Canonical BRD §1C labor trades. Hardcoded here intentionally — these are
# stable taxonomy, not market-volatile data, so they belong in code.
# The DB ``labor_rates`` table is keyed on these trade slugs.
LABOR_TRADES_IN_SCOPE = (
    "woodworking",
    "welding_metal",
    "upholstery",
    "finishing",
    "assembly",
)
COST_BASIS_IN_SCOPE = ("kg", "m2", "m3", "linear_m", "piece")
COMPLEXITY_LEVELS_IN_SCOPE = ("simple", "moderate", "complex", "highly_complex")


# ── Request schema ──────────────────────────────────────────────────────────


class CostLineInput(BaseModel):
    """Optional caller-supplied material or hardware line override."""
    name: str
    basis: str = Field(description="kg / m2 / m3 / linear_m / piece")
    quantity: float = Field(ge=0)
    unit_rate_inr: float = Field(ge=0)


class CostEngineRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    piece_name: str = Field(default="Primary piece", max_length=160)
    theme: str = Field(default="", max_length=64)
    parametric_spec: dict[str, Any] | None = None
    material_spec: dict[str, Any] | None = None
    manufacturing_spec: dict[str, Any] | None = None
    city: str = Field(default="", max_length=80)
    market_segment: str = Field(default="mass_market", max_length=32)
    complexity: str = Field(default="moderate", max_length=32)
    hardware_piece_count: int = Field(default=0, ge=0, le=2000)
    overrides: list[CostLineInput] = Field(default_factory=list)


# ── Knowledge slice ─────────────────────────────────────────────────────────


async def build_cost_engine_knowledge(
    req: CostEngineRequest,
    *,
    session: AsyncSession,
    when: datetime | None = None,
) -> dict[str, Any]:
    """Assemble the BRD knowledge slice the cost-engine LLM stage will see.

    Stage 1 — DB-backed. ``cost_brd``, ``materials_kb`` and
    ``city_price_index`` come from versioned ``app.repositories.pricing``
    rows. The shape is preserved 1:1 with the legacy hardcoded path so
    the system prompt + JSON schema below continue to work unchanged.

    Pass ``when`` (UTC) to reproduce a historical knowledge slice — the
    pricing repos honour ``effective_from / effective_to``.
    """
    # Stage 3A: theme rule pack now comes from the DB-backed
    # ``themes`` table via ``app.services.themes.get_theme``. The
    # accessor falls back to the legacy literal if the DB is empty
    # (fresh-dev scenarios), so this remains safe in all envs.
    pack = await get_theme(session, req.theme) if req.theme else None

    # Pull the DB-backed core (cost factors, labor rates, trade hours,
    # city index, materials KB, source_versions for transparency).
    core = await build_pricing_knowledge(
        session,
        project_name=req.project_name,
        piece_name=req.piece_name,
        theme=req.theme,
        city=req.city or None,
        market_segment=req.market_segment,
        complexity=req.complexity,
        hardware_piece_count=req.hardware_piece_count,
        parametric_spec=req.parametric_spec,
        material_spec=req.material_spec,
        manufacturing_spec=req.manufacturing_spec,
        overrides=[o.model_dump() for o in (req.overrides or [])],
        when=when,
    )

    # Layer in the non-pricing fields the cost-engine prompt expects.
    # Manufacturing lead times + MOQ remain on the legacy module for
    # now — Stage 3 migrates them.
    core["theme_rule_pack"] = (
        {
            "display_name": (pack or {}).get("display_name") or req.theme,
            "material_palette": (pack or {}).get("material_palette", {}),
            "hardware": (pack or {}).get("hardware", {}),
        }
        if pack
        else None
    )
    core["manufacturing_brd"] = {
        "lead_times_weeks": dict(manufacturing.LEAD_TIMES_WEEKS),
        "moq_units": dict(manufacturing.MOQ),
    }
    core["vocab"] = {
        "labor_trades_in_scope": list(LABOR_TRADES_IN_SCOPE),
        "cost_basis_in_scope": list(COST_BASIS_IN_SCOPE),
        "complexity_levels_in_scope": list(COMPLEXITY_LEVELS_IN_SCOPE),
    }
    return core


# ── System prompt ───────────────────────────────────────────────────────────


COST_ENGINE_SYSTEM_PROMPT = """You are a senior production-cost estimator authoring the *Parametric Cost Engine* (BRD Layer 4A) for a single piece of furniture or millwork.

Read the [KNOWLEDGE] block — BRD cost constants (material rates per kg/m², waste 10–15%, finish 15–25% of material, hardware ₹500–2 000/piece, labor rates per trade, workshop overhead 30–40 % of direct, QC 5–10 % of labor, packaging 10–15 % of product cost), theme rule pack, parametric spec, material spec, manufacturing spec, materials KB unit rates, city price index — and produce a structured cost_engine JSON.

The output stops at TOTAL MANUFACTURING COST. Margin / packaging-to-retail is layered separately in 4B — DO NOT add profit margin or designer markup here.

Studio voice — short, decisive, no marketing prose.

Hard rules for header:
- city_price_index MUST equal project.city_price_index from knowledge.
- market_segment MUST be the value from project (mass_market | luxury).
- complexity MUST be one of complexity_levels_in_scope.

Hard rules for material lines (one per distinct material in material_spec or parametric_spec):
- name: human-readable material name pulled from material_spec/parametric_spec (e.g. "Walnut solid", "MS round bar", "Bouclé fabric").
- basis MUST be in cost_basis_in_scope (kg / m2 / m3 / linear_m / piece). Snap to cost_brd.cost_basis_by_family[family] when a family applies.
- quantity is computed from the parametric_spec (board feet, surface area, mass) — derive it; never invent. Cite the geometric source in rationale.
- unit_rate_inr_per_unit MUST equal materials_kb.wood_inr_kg[species] or .metals_inr_kg[metal] when known; else use the override list project.overrides; else cite an industry typical inside the BRD band and call it out in rationale.
- subtotal_inr = quantity × unit_rate_inr_per_unit (snap to nearest rupee).
- waste_factor_pct MUST sit inside cost_brd.waste_factor_pct_band (10–15). Default to the midpoint 12.5 unless a written reason justifies tighter or looser.
- subtotal_with_waste_inr = round(subtotal_inr × (1 + waste_factor_pct/100), 0).
- Apply the city_price_index AT THE LINE LEVEL only when the material is locally fabricated (wood, custom metal, upholstery). Imported materials carry index = 1.0; cite this distinction.

Hard rules for finish lines (one per material that takes a finish):
- finish_cost_inr = round(linked_material_subtotal_with_waste × pct/100, 0); pct MUST sit inside cost_brd.finish_cost_pct_of_material (15–25).
- linked_material_name MUST match a material line.

Hard rules for hardware lines:
- piece_count MUST equal project.hardware_piece_count when > 0.
- rate_inr_per_piece MUST sit inside cost_brd.hardware_inr_per_piece (500–2 000); pick a value that matches theme.hardware tier (cite which).
- subtotal_inr = piece_count × rate_inr_per_piece.

Material subtotal:
- material_subtotal_inr = sum(material[].subtotal_with_waste_inr) + sum(finish[].finish_cost_inr) + sum(hardware[].subtotal_inr). Re-derive and snap.

Hard rules for labor lines (at least one per relevant trade — pull from manufacturing_spec when present):
- trade MUST be in labor_trades_in_scope (woodworking, welding_metal, upholstery, finishing, assembly).
- hours MUST sit inside cost_brd.trade_hours_by_complexity[trade][project.complexity] band. Cite which band.
- base_rate_inr_hour_band MUST equal cost_brd.labor_rates_inr_hour[trade] verbatim (e.g. [200, 400] for woodworking).
- effective_rate_inr_hour = round(midpoint(base_rate_band) × city_price_index, 0). Cite the index.
- subtotal_inr = round(hours × effective_rate_inr_hour, 0).
- Drop trades that are clearly not used (e.g. omit welding_metal for an all-wood piece) and state it in assumptions.

Labor subtotal:
- labor_subtotal_inr = sum(labor[].subtotal_inr).

Hard rules for overhead lines (BRD bullets — every one of the three MUST be present):
- workshop_allocation: pct MUST sit inside cost_brd.workshop_overhead_pct_of_direct (30–40). base = material_subtotal + labor_subtotal. amount_inr = round(base × pct/100, 0). Default pct = 35 (band midpoint); deviation requires a written reason.
- quality_control: pct MUST sit inside cost_brd.qc_pct_of_labor (5–10). base = labor_subtotal. amount_inr = round(base × pct/100, 0).
- packaging_shipping: pct MUST sit inside cost_brd.packaging_logistics_pct_of_product (10–15). base = product_cost = material_subtotal + labor_subtotal + workshop_allocation_amount_inr (i.e. apply AFTER workshop overhead is folded in, since it is a percentage of "product cost"). amount_inr = round(base × pct/100, 0).

Overhead subtotal:
- overhead_subtotal_inr = workshop_allocation.amount_inr + quality_control.amount_inr + packaging_shipping.amount_inr.

Total manufacturing cost:
- total_manufacturing_cost_inr = material_subtotal_inr + labor_subtotal_inr + overhead_subtotal_inr.

Currency MUST be "INR".
assumptions[] cites every divergence (e.g. waste set tighter for sheet goods; QC pct 8% because of finish-critical surfaces; complex Mortise count drove woodworking hours to band-high).

Never invent BRD constants — every percentage, every rate, every hour-by-complexity band MUST come from the knowledge block."""


# ── JSON schema ─────────────────────────────────────────────────────────────


def _material_line_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},                          # M1, M2 ...
            "name": {"type": "string"},
            "family": {"type": "string"},                       # wood_solid / metal / fabric ...
            "basis": {"type": "string"},                        # kg / m2 / m3 / linear_m / piece
            "quantity": {"type": "number"},
            "unit_rate_inr_per_unit": {"type": "number"},
            "subtotal_inr": {"type": "number"},
            "waste_factor_pct": {"type": "number"},
            "subtotal_with_waste_inr": {"type": "number"},
            "city_index_applied": {"type": "number"},           # 1.0 for imported, project index otherwise
            "rationale": {"type": "string"},
        },
        "required": [
            "key", "name", "family", "basis", "quantity",
            "unit_rate_inr_per_unit", "subtotal_inr",
            "waste_factor_pct", "subtotal_with_waste_inr",
            "city_index_applied", "rationale",
        ],
        "additionalProperties": False,
    }


def _finish_line_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "name": {"type": "string"},
            "linked_material_name": {"type": "string"},
            "linked_material_subtotal_with_waste_inr": {"type": "number"},
            "pct": {"type": "number"},
            "finish_cost_inr": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": [
            "key", "name", "linked_material_name",
            "linked_material_subtotal_with_waste_inr",
            "pct", "finish_cost_inr", "rationale",
        ],
        "additionalProperties": False,
    }


def _hardware_line_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "name": {"type": "string"},
            "piece_count": {"type": "integer"},
            "rate_inr_per_piece": {"type": "number"},
            "subtotal_inr": {"type": "number"},
            "tier": {"type": "string"},                # "studio" / "premium" / "designer"
            "rationale": {"type": "string"},
        },
        "required": [
            "key", "name", "piece_count", "rate_inr_per_piece",
            "subtotal_inr", "tier", "rationale",
        ],
        "additionalProperties": False,
    }


def _labor_line_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "key": {"type": "string"},
            "trade": {"type": "string"},
            "hours": {"type": "number"},
            "complexity_band_used": {
                "type": "array",
                "items": {"type": "number"},   # [low, high] hours band cited
            },
            "base_rate_inr_hour_band": {
                "type": "array",
                "items": {"type": "number"},   # [low, high]
            },
            "effective_rate_inr_hour": {"type": "number"},
            "subtotal_inr": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": [
            "key", "trade", "hours", "complexity_band_used",
            "base_rate_inr_hour_band", "effective_rate_inr_hour",
            "subtotal_inr", "rationale",
        ],
        "additionalProperties": False,
    }


def _overhead_block_schema() -> dict[str, Any]:
    sub = {
        "type": "object",
        "properties": {
            "pct": {"type": "number"},
            "pct_band_brd": {
                "type": "array",
                "items": {"type": "number"},
            },
            "base_inr": {"type": "number"},
            "base_description": {"type": "string"},
            "amount_inr": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": [
            "pct", "pct_band_brd", "base_inr",
            "base_description", "amount_inr", "rationale",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "workshop_allocation": sub,
            "quality_control": sub,
            "packaging_shipping": sub,
            "overhead_subtotal_inr": {"type": "number"},
        },
        "required": [
            "workshop_allocation", "quality_control",
            "packaging_shipping", "overhead_subtotal_inr",
        ],
        "additionalProperties": False,
    }


COST_ENGINE_SCHEMA: dict[str, Any] = {
    "name": "cost_engine",
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
                    "city_price_index": {"type": "number"},
                    "market_segment": {"type": "string"},
                    "complexity": {"type": "string"},
                    "currency": {"type": "string"},
                    "date_iso": {"type": "string"},
                },
                "required": [
                    "project", "piece_name", "theme", "city",
                    "city_price_index", "market_segment", "complexity",
                    "currency", "date_iso",
                ],
                "additionalProperties": False,
            },
            "material_cost": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "array",
                        "items": _material_line_schema(),
                    },
                    "finishes": {
                        "type": "array",
                        "items": _finish_line_schema(),
                    },
                    "hardware": {
                        "type": "array",
                        "items": _hardware_line_schema(),
                    },
                    "material_subtotal_inr": {"type": "number"},
                },
                "required": [
                    "lines", "finishes", "hardware", "material_subtotal_inr",
                ],
                "additionalProperties": False,
            },
            "labor_cost": {
                "type": "object",
                "properties": {
                    "lines": {
                        "type": "array",
                        "items": _labor_line_schema(),
                    },
                    "labor_subtotal_inr": {"type": "number"},
                },
                "required": ["lines", "labor_subtotal_inr"],
                "additionalProperties": False,
            },
            "overhead": _overhead_block_schema(),
            "total_manufacturing_cost_inr": {"type": "number"},
            "summary": {
                "type": "object",
                "properties": {
                    "material_pct_of_total": {"type": "number"},
                    "labor_pct_of_total": {"type": "number"},
                    "overhead_pct_of_total": {"type": "number"},
                },
                "required": [
                    "material_pct_of_total",
                    "labor_pct_of_total",
                    "overhead_pct_of_total",
                ],
                "additionalProperties": False,
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header", "material_cost", "labor_cost", "overhead",
            "total_manufacturing_cost_inr", "summary", "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: CostEngineRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Piece: {req.piece_name}\n"
        f"- Theme: {req.theme or '(not specified)'}\n"
        f"- City: {req.city or '(not specified)'}\n"
        f"- Market segment: {req.market_segment}\n"
        f"- Complexity: {req.complexity}\n"
        f"- Hardware piece count: {req.hardware_piece_count}\n"
        f"- Date (UTC ISO): {today}\n\n"
        "Produce the cost_engine JSON. Cover material_cost (lines + "
        "finishes + hardware + material_subtotal), labor_cost "
        "(lines + labor_subtotal), overhead (workshop_allocation + "
        "quality_control + packaging_shipping + overhead_subtotal), "
        "and total_manufacturing_cost_inr. Stop at TOTAL MANUFACTURING "
        "COST — do not apply profit margin or designer markup. Snap "
        "every number to BRD bands; cite the row used in rationale."
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
    brd = knowledge.get("cost_brd", {}) or {}
    project = knowledge.get("project", {}) or {}
    out: dict[str, list[Any]] = {
        "bad_currency": [],
        "bad_city_index": [],
        "bad_market_segment": [],
        "bad_complexity": [],
        "bad_basis": [],
        "bad_waste_factor": [],
        "bad_material_subtotal": [],
        "bad_material_with_waste": [],
        "bad_finish_pct": [],
        "bad_finish_amount": [],
        "missing_finish_link": [],
        "bad_hardware_rate": [],
        "bad_hardware_count": [],
        "bad_hardware_subtotal": [],
        "bad_material_subtotal_total": [],
        "bad_labor_trade": [],
        "labor_hours_out_of_band": [],
        "bad_base_rate_band": [],
        "bad_effective_rate": [],
        "bad_labor_subtotal": [],
        "bad_labor_subtotal_total": [],
        "missing_overhead_section": [],
        "bad_workshop_pct": [],
        "bad_workshop_base": [],
        "bad_workshop_amount": [],
        "bad_qc_pct": [],
        "bad_qc_base": [],
        "bad_qc_amount": [],
        "bad_packaging_pct": [],
        "bad_packaging_base": [],
        "bad_packaging_amount": [],
        "bad_overhead_subtotal": [],
        "bad_total_manufacturing_cost": [],
        "bad_summary_pct": [],
    }

    # Header.
    header = spec.get("header") or {}
    if (header.get("currency") or "").upper() != "INR":
        out["bad_currency"].append(header.get("currency"))
    if not _approx_eq(header.get("city_price_index"), project.get("city_price_index"), tol=0.001):
        out["bad_city_index"].append({
            "expected": project.get("city_price_index"),
            "actual": header.get("city_price_index"),
        })
    if (header.get("market_segment") or "").lower() != (project.get("market_segment") or "").lower():
        out["bad_market_segment"].append({
            "expected": project.get("market_segment"),
            "actual": header.get("market_segment"),
        })
    if (header.get("complexity") or "").lower() not in COMPLEXITY_LEVELS_IN_SCOPE:
        out["bad_complexity"].append(header.get("complexity"))

    # Material lines.
    material = spec.get("material_cost") or {}
    lines = material.get("lines") or []
    finishes = material.get("finishes") or []
    hardware = material.get("hardware") or []

    waste_band = brd.get("waste_factor_pct_band") or [10, 15]
    finish_band = brd.get("finish_cost_pct_of_material") or [15, 25]
    hardware_band = brd.get("hardware_inr_per_piece") or [500, 2000]

    sum_material_with_waste = 0.0
    line_index: dict[str, dict] = {}
    for line in lines:
        line_index[line.get("name") or ""] = line
        basis = (line.get("basis") or "").lower()
        if basis not in COST_BASIS_IN_SCOPE:
            out["bad_basis"].append({"name": line.get("name"), "basis": basis or "<missing>"})

        wf = line.get("waste_factor_pct")
        if wf is None or not _within(wf, waste_band):
            out["bad_waste_factor"].append({
                "name": line.get("name"), "value": wf, "band": list(waste_band),
            })

        qty = float(line.get("quantity") or 0)
        rate = float(line.get("unit_rate_inr_per_unit") or 0)
        index = float(line.get("city_index_applied") or 1.0)
        expected_subtotal = round(qty * rate * index, 0)
        if not _approx_eq(line.get("subtotal_inr"), expected_subtotal, tol=2.0):
            out["bad_material_subtotal"].append({
                "name": line.get("name"),
                "expected": expected_subtotal, "actual": line.get("subtotal_inr"),
            })

        if wf is not None and line.get("subtotal_inr") is not None:
            expected_with_waste = round(float(line["subtotal_inr"]) * (1 + float(wf) / 100), 0)
            if not _approx_eq(line.get("subtotal_with_waste_inr"), expected_with_waste, tol=2.0):
                out["bad_material_with_waste"].append({
                    "name": line.get("name"),
                    "expected": expected_with_waste,
                    "actual": line.get("subtotal_with_waste_inr"),
                })
        sum_material_with_waste += float(line.get("subtotal_with_waste_inr") or 0)

    # Finish lines.
    sum_finish = 0.0
    for f in finishes:
        link = f.get("linked_material_name")
        if link and link not in line_index:
            out["missing_finish_link"].append({"finish": f.get("name"), "link": link})
        pct = f.get("pct")
        if pct is None or not _within(pct, finish_band):
            out["bad_finish_pct"].append({
                "finish": f.get("name"), "value": pct, "band": list(finish_band),
            })
        base = f.get("linked_material_subtotal_with_waste_inr") or 0
        expected_amount = round(float(base) * float(pct or 0) / 100, 0)
        if not _approx_eq(f.get("finish_cost_inr"), expected_amount, tol=2.0):
            out["bad_finish_amount"].append({
                "finish": f.get("name"),
                "expected": expected_amount, "actual": f.get("finish_cost_inr"),
            })
        sum_finish += float(f.get("finish_cost_inr") or 0)

    # Hardware lines.
    sum_hardware = 0.0
    project_pieces = int(project.get("hardware_piece_count") or 0)
    declared_pieces = sum(int(h.get("piece_count") or 0) for h in hardware)
    if project_pieces > 0 and declared_pieces != project_pieces:
        out["bad_hardware_count"].append({
            "expected_total": project_pieces, "actual_total": declared_pieces,
        })
    for h in hardware:
        rate = h.get("rate_inr_per_piece")
        if rate is None or not _within(rate, hardware_band):
            out["bad_hardware_rate"].append({
                "name": h.get("name"), "value": rate, "band": list(hardware_band),
            })
        expected_sub = round(float(h.get("piece_count") or 0) * float(rate or 0), 0)
        if not _approx_eq(h.get("subtotal_inr"), expected_sub, tol=2.0):
            out["bad_hardware_subtotal"].append({
                "name": h.get("name"),
                "expected": expected_sub, "actual": h.get("subtotal_inr"),
            })
        sum_hardware += float(h.get("subtotal_inr") or 0)

    # Material subtotal total.
    expected_material_subtotal = round(sum_material_with_waste + sum_finish + sum_hardware, 0)
    if not _approx_eq(material.get("material_subtotal_inr"), expected_material_subtotal, tol=2.0):
        out["bad_material_subtotal_total"].append({
            "expected": expected_material_subtotal,
            "actual": material.get("material_subtotal_inr"),
        })

    # Labor.
    labor = spec.get("labor_cost") or {}
    labor_lines = labor.get("lines") or []
    labor_rates = brd.get("labor_rates_inr_hour", {}) or {}
    hours_table = brd.get("trade_hours_by_complexity", {}) or {}
    complexity = (project.get("complexity") or "moderate").lower()
    city_index = float(project.get("city_price_index") or 1.0)

    sum_labor = 0.0
    for ln in labor_lines:
        trade = (ln.get("trade") or "").lower()
        if trade not in LABOR_TRADES_IN_SCOPE:
            out["bad_labor_trade"].append(trade or "<missing>")
            continue
        # Hours band.
        band = (hours_table.get(trade) or {}).get(complexity)
        if band and not _within(ln.get("hours"), band):
            out["labor_hours_out_of_band"].append({
                "trade": trade, "complexity": complexity,
                "band": list(band), "actual": ln.get("hours"),
            })
        # Base rate band.
        expected_band = labor_rates.get(trade)
        actual_band = ln.get("base_rate_inr_hour_band") or []
        if expected_band and (
            len(actual_band) != 2
            or not _approx_eq(actual_band[0], expected_band[0])
            or not _approx_eq(actual_band[1], expected_band[1])
        ):
            out["bad_base_rate_band"].append({
                "trade": trade,
                "expected": list(expected_band), "actual": list(actual_band),
            })
        # Effective rate ≈ midpoint × city_index.
        if expected_band:
            mid = (float(expected_band[0]) + float(expected_band[1])) / 2.0
            expected_rate = round(mid * city_index, 0)
            if not _approx_eq(ln.get("effective_rate_inr_hour"), expected_rate, tol=2.0):
                out["bad_effective_rate"].append({
                    "trade": trade, "expected": expected_rate,
                    "actual": ln.get("effective_rate_inr_hour"),
                })
        # Subtotal = hours × effective_rate.
        expected_subtotal = round(
            float(ln.get("hours") or 0) * float(ln.get("effective_rate_inr_hour") or 0), 0
        )
        if not _approx_eq(ln.get("subtotal_inr"), expected_subtotal, tol=2.0):
            out["bad_labor_subtotal"].append({
                "trade": trade,
                "expected": expected_subtotal, "actual": ln.get("subtotal_inr"),
            })
        sum_labor += float(ln.get("subtotal_inr") or 0)

    if not _approx_eq(labor.get("labor_subtotal_inr"), round(sum_labor, 0), tol=2.0):
        out["bad_labor_subtotal_total"].append({
            "expected": round(sum_labor, 0), "actual": labor.get("labor_subtotal_inr"),
        })

    # Overhead.
    overhead = spec.get("overhead") or {}
    workshop_band = brd.get("workshop_overhead_pct_of_direct") or [30, 40]
    qc_band = brd.get("qc_pct_of_labor") or [5, 10]
    packaging_band = brd.get("packaging_logistics_pct_of_product") or [10, 15]
    material_subtotal = float(material.get("material_subtotal_inr") or 0)
    labor_subtotal = float(labor.get("labor_subtotal_inr") or 0)
    direct = material_subtotal + labor_subtotal

    for section in ("workshop_allocation", "quality_control", "packaging_shipping"):
        if not overhead.get(section):
            out["missing_overhead_section"].append(section)

    ws = overhead.get("workshop_allocation") or {}
    if ws.get("pct") is not None and not _within(ws["pct"], workshop_band):
        out["bad_workshop_pct"].append({
            "value": ws["pct"], "band": list(workshop_band),
        })
    if not _approx_eq(ws.get("base_inr"), round(direct, 0), tol=2.0):
        out["bad_workshop_base"].append({
            "expected": round(direct, 0), "actual": ws.get("base_inr"),
        })
    expected_ws_amount = round(direct * float(ws.get("pct") or 0) / 100, 0)
    if not _approx_eq(ws.get("amount_inr"), expected_ws_amount, tol=2.0):
        out["bad_workshop_amount"].append({
            "expected": expected_ws_amount, "actual": ws.get("amount_inr"),
        })
    workshop_amount = float(ws.get("amount_inr") or 0)

    qc = overhead.get("quality_control") or {}
    if qc.get("pct") is not None and not _within(qc["pct"], qc_band):
        out["bad_qc_pct"].append({"value": qc["pct"], "band": list(qc_band)})
    if not _approx_eq(qc.get("base_inr"), round(labor_subtotal, 0), tol=2.0):
        out["bad_qc_base"].append({
            "expected": round(labor_subtotal, 0), "actual": qc.get("base_inr"),
        })
    expected_qc_amount = round(labor_subtotal * float(qc.get("pct") or 0) / 100, 0)
    if not _approx_eq(qc.get("amount_inr"), expected_qc_amount, tol=2.0):
        out["bad_qc_amount"].append({
            "expected": expected_qc_amount, "actual": qc.get("amount_inr"),
        })
    qc_amount = float(qc.get("amount_inr") or 0)

    pk = overhead.get("packaging_shipping") or {}
    product_cost = direct + workshop_amount
    if pk.get("pct") is not None and not _within(pk["pct"], packaging_band):
        out["bad_packaging_pct"].append({
            "value": pk["pct"], "band": list(packaging_band),
        })
    if not _approx_eq(pk.get("base_inr"), round(product_cost, 0), tol=2.0):
        out["bad_packaging_base"].append({
            "expected": round(product_cost, 0), "actual": pk.get("base_inr"),
        })
    expected_pk_amount = round(product_cost * float(pk.get("pct") or 0) / 100, 0)
    if not _approx_eq(pk.get("amount_inr"), expected_pk_amount, tol=2.0):
        out["bad_packaging_amount"].append({
            "expected": expected_pk_amount, "actual": pk.get("amount_inr"),
        })
    pk_amount = float(pk.get("amount_inr") or 0)

    expected_overhead_subtotal = round(workshop_amount + qc_amount + pk_amount, 0)
    if not _approx_eq(overhead.get("overhead_subtotal_inr"), expected_overhead_subtotal, tol=2.0):
        out["bad_overhead_subtotal"].append({
            "expected": expected_overhead_subtotal,
            "actual": overhead.get("overhead_subtotal_inr"),
        })

    # Total manufacturing cost.
    expected_total = round(material_subtotal + labor_subtotal + expected_overhead_subtotal, 0)
    if not _approx_eq(spec.get("total_manufacturing_cost_inr"), expected_total, tol=2.0):
        out["bad_total_manufacturing_cost"].append({
            "expected": expected_total,
            "actual": spec.get("total_manufacturing_cost_inr"),
        })

    # Summary percentages must add to ~100.
    summary = spec.get("summary") or {}
    pct_total = (
        float(summary.get("material_pct_of_total") or 0)
        + float(summary.get("labor_pct_of_total") or 0)
        + float(summary.get("overhead_pct_of_total") or 0)
    )
    if expected_total > 0 and abs(pct_total - 100) > 0.5:
        out["bad_summary_pct"].append({"expected_sum_pct": 100, "actual_sum_pct": pct_total})

    return {
        "currency_is_inr": not out["bad_currency"],
        "bad_currency": out["bad_currency"],
        "city_index_matches": not out["bad_city_index"],
        "bad_city_index": out["bad_city_index"],
        "market_segment_matches": not out["bad_market_segment"],
        "bad_market_segment": out["bad_market_segment"],
        "complexity_in_scope": not out["bad_complexity"],
        "bad_complexity": out["bad_complexity"],
        "material_basis_in_scope": not out["bad_basis"],
        "bad_basis": out["bad_basis"],
        "waste_factor_in_band": not out["bad_waste_factor"],
        "bad_waste_factor": out["bad_waste_factor"],
        "material_subtotal_consistent": not out["bad_material_subtotal"],
        "bad_material_subtotal": out["bad_material_subtotal"],
        "material_with_waste_consistent": not out["bad_material_with_waste"],
        "bad_material_with_waste": out["bad_material_with_waste"],
        "finish_pct_in_band": not out["bad_finish_pct"],
        "bad_finish_pct": out["bad_finish_pct"],
        "finish_amount_consistent": not out["bad_finish_amount"],
        "bad_finish_amount": out["bad_finish_amount"],
        "finish_links_to_material": not out["missing_finish_link"],
        "missing_finish_link": out["missing_finish_link"],
        "hardware_rate_in_band": not out["bad_hardware_rate"],
        "bad_hardware_rate": out["bad_hardware_rate"],
        "hardware_count_matches_brief": not out["bad_hardware_count"],
        "bad_hardware_count": out["bad_hardware_count"],
        "hardware_subtotal_consistent": not out["bad_hardware_subtotal"],
        "bad_hardware_subtotal": out["bad_hardware_subtotal"],
        "material_subtotal_total_consistent": not out["bad_material_subtotal_total"],
        "bad_material_subtotal_total": out["bad_material_subtotal_total"],
        "labor_trade_in_scope": not out["bad_labor_trade"],
        "bad_labor_trade": out["bad_labor_trade"],
        "labor_hours_in_complexity_band": not out["labor_hours_out_of_band"],
        "labor_hours_out_of_band": out["labor_hours_out_of_band"],
        "labor_base_rate_band_matches_brd": not out["bad_base_rate_band"],
        "bad_base_rate_band": out["bad_base_rate_band"],
        "labor_effective_rate_consistent": not out["bad_effective_rate"],
        "bad_effective_rate": out["bad_effective_rate"],
        "labor_subtotal_consistent": not out["bad_labor_subtotal"],
        "bad_labor_subtotal": out["bad_labor_subtotal"],
        "labor_subtotal_total_consistent": not out["bad_labor_subtotal_total"],
        "bad_labor_subtotal_total": out["bad_labor_subtotal_total"],
        "all_overhead_sections_present": not out["missing_overhead_section"],
        "missing_overhead_section": out["missing_overhead_section"],
        "workshop_pct_in_band": not out["bad_workshop_pct"],
        "bad_workshop_pct": out["bad_workshop_pct"],
        "workshop_base_is_direct_cost": not out["bad_workshop_base"],
        "bad_workshop_base": out["bad_workshop_base"],
        "workshop_amount_consistent": not out["bad_workshop_amount"],
        "bad_workshop_amount": out["bad_workshop_amount"],
        "qc_pct_in_band": not out["bad_qc_pct"],
        "bad_qc_pct": out["bad_qc_pct"],
        "qc_base_is_labor": not out["bad_qc_base"],
        "bad_qc_base": out["bad_qc_base"],
        "qc_amount_consistent": not out["bad_qc_amount"],
        "bad_qc_amount": out["bad_qc_amount"],
        "packaging_pct_in_band": not out["bad_packaging_pct"],
        "bad_packaging_pct": out["bad_packaging_pct"],
        "packaging_base_is_product_cost": not out["bad_packaging_base"],
        "bad_packaging_base": out["bad_packaging_base"],
        "packaging_amount_consistent": not out["bad_packaging_amount"],
        "bad_packaging_amount": out["bad_packaging_amount"],
        "overhead_subtotal_consistent": not out["bad_overhead_subtotal"],
        "bad_overhead_subtotal": out["bad_overhead_subtotal"],
        "total_manufacturing_cost_consistent": not out["bad_total_manufacturing_cost"],
        "bad_total_manufacturing_cost": out["bad_total_manufacturing_cost"],
        "summary_pct_sums_to_100": not out["bad_summary_pct"],
        "bad_summary_pct": out["bad_summary_pct"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class CostEngineError(RuntimeError):
    """Raised when the LLM cost engine stage cannot produce a grounded sheet."""


async def generate_cost_engine(
    req: CostEngineRequest,
    *,
    session: AsyncSession,
    snapshot_id: str | None = None,
    actor_id: str | None = None,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Run the parametric cost-engine stage.

    Stage 1 — DB-backed knowledge + immutable snapshots.

    Modes
    -----
    - **Live** (default): builds knowledge from current DB rows and
      records a fresh :class:`PricingSnapshot`. The returned dict
      includes ``pricing_snapshot_id`` so callers can attach the
      snapshot to their own artefact (estimate row, project log, …).
    - **Replay**: pass ``snapshot_id`` to re-run the LLM against the
      *exact* knowledge dict that was captured before. No new snapshot
      is recorded; ``pricing_snapshot_id`` echoes the input id.

    Args
    ----
    session: caller-managed transaction. The snapshot insert flushes
        but does not commit; the route owns the commit.
    snapshot_id: replay an existing capture instead of building fresh.
    actor_id / project_id: provenance metadata for the snapshot row.
    """
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise CostEngineError(
            "OpenAI API key is not configured. The cost engine stage requires "
            "a live LLM call; no static fallback is served."
        )

    if req.complexity.lower() not in COMPLEXITY_LEVELS_IN_SCOPE:
        raise CostEngineError(
            f"Unknown complexity '{req.complexity}'. Pick one of: "
            f"{', '.join(COMPLEXITY_LEVELS_IN_SCOPE)}."
        )
    if req.market_segment.lower() not in {"mass_market", "luxury"}:
        raise CostEngineError(
            f"Unknown market_segment '{req.market_segment}'. "
            f"Pick 'mass_market' or 'luxury'."
        )

    # ── Knowledge: replay or build fresh ────────────────────────────
    if snapshot_id is not None:
        knowledge = await load_snapshot(session, snapshot_id)
        if knowledge is None:
            raise CostEngineError(
                f"Pricing snapshot {snapshot_id!r} not found"
            )
        recorded_snapshot_id = snapshot_id
    else:
        knowledge = await build_cost_engine_knowledge(req, session=session)
        snapshot = await record_snapshot(
            session,
            knowledge=knowledge,
            target_type="cost_engine",
            target_id=None,
            project_id=project_id,
            actor_id=actor_id,
            actor_kind="user" if actor_id else "system",
        )
        recorded_snapshot_id = snapshot["id"]

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": COST_ENGINE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": COST_ENGINE_SCHEMA,
            },
            temperature=0.2,
            max_tokens=2400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for cost engine")
        raise CostEngineError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CostEngineError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    return {
        "id": "cost_engine",
        "name": "Parametric Cost Engine",
        "model": settings.openai_model,
        "city": req.city or None,
        "knowledge": knowledge,
        "cost_engine": spec,
        "validation": validation,
        "pricing_snapshot_id": recorded_snapshot_id,
    }
