"""LLM-driven Sensitivity Analysis (BRD Layer 4D).

What-if report layered on top of 4A (cost engine) and 4B (pricing
buildup). Answers four questions:

    ├── If material +10% → final price increases by [%]
    ├── If labor    +10% → final price increases by [%]
    ├── If overhead +10% → final price increases by [%]
    └── Cost at different volumes (1 piece, 5 pieces, 10 pieces)

Pipeline contract — same as every other LLM service:

    INPUT (cost_engine + pricing_buildup objects + scenario flags)
      → INJECT  (BRD constants + DETERMINISTIC re-walk of every
                 scenario; the LLM never invents numbers)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (every shocked total, every uplift %, every volume
                   manufacturer-margin band exactly matches the
                   deterministic rerun in the knowledge slice)
      → OUTPUT  (sensitivity_analysis JSON conforming to the BRD
                 template)

The deterministic re-walk lives here so the math is unambiguous: a
shock to material/labor cascades through workshop overhead (% of
direct) and packaging (% of product cost), then through every active
margin/markup layer to the final retail price. The LLM's job is to
narrate the table, not to compute it.
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


SHOCK_PCT_DEFAULT = 10.0
DEFAULT_VOLUMES = (1, 5, 10)


def _volume_tier_for_units(units: int) -> str:
    """Map a unit count to the BRD manufacturer-margin volume tier."""
    if units <= 1:
        return "one_off"
    if units <= 25:
        return "small_batch"
    if units <= 250:
        return "production"
    return "mass_production"


# ── Request schema ──────────────────────────────────────────────────────────


class SensitivityRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    piece_name: str = Field(default="Primary piece", max_length=160)
    city: str = Field(default="", max_length=80)
    cost_engine: dict[str, Any] = Field(
        ..., description="The 4A cost_engine spec object."
    )
    pricing_buildup: dict[str, Any] = Field(
        ..., description="The 4B pricing_buildup spec object."
    )
    shock_pct: float = Field(default=SHOCK_PCT_DEFAULT, ge=0, le=50)
    volumes: list[int] = Field(default_factory=lambda: list(DEFAULT_VOLUMES))


# ── Deterministic price-walk re-runner ──────────────────────────────────────


def _extract_inputs(req: SensitivityRequest) -> dict[str, Any]:
    """Pull every dial we need from the upstream specs."""
    ce = req.cost_engine or {}
    pb = req.pricing_buildup or {}
    overhead = ce.get("overhead") or {}

    workshop = overhead.get("workshop_allocation") or {}
    qc = overhead.get("quality_control") or {}
    packaging = overhead.get("packaging_shipping") or {}

    return {
        "material_inr": float((ce.get("material_cost") or {}).get("material_subtotal_inr") or 0),
        "labor_inr": float((ce.get("labor_cost") or {}).get("labor_subtotal_inr") or 0),
        "overhead_inr": float(overhead.get("overhead_subtotal_inr") or 0),
        "workshop_pct": float(workshop.get("pct") or 0),
        "qc_pct": float(qc.get("pct") or 0),
        "packaging_pct": float(packaging.get("pct") or 0),
        "manufacturing_cost_inr": float(ce.get("total_manufacturing_cost_inr") or 0),
        "final_retail_price_inr": float(pb.get("final_retail_price_inr") or 0),
        "manufacturer_margin": pb.get("manufacturer_margin") or {},
        "designer_margin": pb.get("designer_margin") or {},
        "retail_markup": pb.get("retail_markup") or {},
        "customization_premium": pb.get("customization_premium") or {},
        "header_volume_tier": (pb.get("header") or {}).get("volume_tier"),
    }


def _recompute_overhead(material: float, labor: float, *,
                        workshop_pct: float, qc_pct: float,
                        packaging_pct: float) -> dict[str, float]:
    """Re-derive the BRD overhead stack from material + labor."""
    direct = material + labor
    workshop_amt = round(direct * workshop_pct / 100, 0)
    qc_amt = round(labor * qc_pct / 100, 0)
    product_cost = direct + workshop_amt
    packaging_amt = round(product_cost * packaging_pct / 100, 0)
    overhead_total = round(workshop_amt + qc_amt + packaging_amt, 0)
    return {
        "direct_inr": round(direct, 0),
        "workshop_amt_inr": workshop_amt,
        "qc_amt_inr": qc_amt,
        "product_cost_inr": round(product_cost, 0),
        "packaging_amt_inr": packaging_amt,
        "overhead_inr": overhead_total,
    }


def _layer_amount(running_total: float, layer: dict[str, Any],
                  *, override_pct: float | None = None) -> tuple[float, float]:
    """Apply one BRD margin/markup layer. Returns (amount, new_running_total)."""
    if not layer.get("applies"):
        return 0.0, round(running_total, 0)
    pct = float(override_pct if override_pct is not None else (layer.get("pct") or 0))
    amt = round(running_total * pct / 100, 0)
    return amt, round(running_total + amt, 0)


def _walk_price(*, manufacturing_cost: float, inputs: dict[str, Any],
                manufacturer_pct: float | None = None) -> dict[str, float]:
    """Re-walk the BRD 4B margin stack with optional manufacturer pct override."""
    mm_amt, ex_factory = _layer_amount(
        manufacturing_cost, inputs["manufacturer_margin"],
        override_pct=manufacturer_pct,
    )
    dm_amt, trade = _layer_amount(ex_factory, inputs["designer_margin"])
    rm_amt, retail_base = _layer_amount(trade, inputs["retail_markup"])
    cp_amt, final = _layer_amount(retail_base, inputs["customization_premium"])
    return {
        "manufacturing_cost_inr": round(manufacturing_cost, 0),
        "manufacturer_margin_amt_inr": mm_amt,
        "ex_factory_price_inr": ex_factory,
        "designer_margin_amt_inr": dm_amt,
        "trade_price_inr": trade,
        "retail_markup_amt_inr": rm_amt,
        "retail_base_inr": retail_base,
        "customization_premium_amt_inr": cp_amt,
        "final_retail_price_inr": final,
    }


def _build_shock_scenario(label: str, *, shocked_component: str,
                          shock_pct: float, inputs: dict[str, Any]) -> dict[str, Any]:
    """Apply +shock_pct to one of {material, labor, overhead} and re-walk."""
    material = inputs["material_inr"]
    labor = inputs["labor_inr"]
    if shocked_component == "material":
        material = round(material * (1 + shock_pct / 100), 0)
    elif shocked_component == "labor":
        labor = round(labor * (1 + shock_pct / 100), 0)
    elif shocked_component == "overhead":
        # Overhead shock keeps direct constant; bumps the overhead
        # subtotal by shock_pct directly. Workshop / QC / packaging
        # amounts are scaled in lock-step.
        pass
    else:
        raise ValueError(f"Unknown shocked_component '{shocked_component}'")

    if shocked_component in {"material", "labor"}:
        oh = _recompute_overhead(
            material, labor,
            workshop_pct=inputs["workshop_pct"],
            qc_pct=inputs["qc_pct"],
            packaging_pct=inputs["packaging_pct"],
        )
        new_overhead_total = oh["overhead_inr"]
    else:
        new_overhead_total = round(inputs["overhead_inr"] * (1 + shock_pct / 100), 0)

    new_mfg = round(material + labor + new_overhead_total, 0)
    walk = _walk_price(manufacturing_cost=new_mfg, inputs=inputs)
    base_retail = inputs["final_retail_price_inr"]
    delta_inr = round(walk["final_retail_price_inr"] - base_retail, 0)
    delta_pct = (
        round(delta_inr / base_retail * 100, 2) if base_retail > 0 else 0.0
    )
    return {
        "label": label,
        "shocked_component": shocked_component,
        "shock_pct": shock_pct,
        "new_material_inr": round(material, 0),
        "new_labor_inr": round(labor, 0),
        "new_overhead_inr": new_overhead_total,
        "new_manufacturing_cost_inr": new_mfg,
        "new_final_retail_price_inr": walk["final_retail_price_inr"],
        "delta_inr": delta_inr,
        "delta_pct_of_retail": delta_pct,
    }


def _build_volume_scenario(units: int, inputs: dict[str, Any]) -> dict[str, Any]:
    """Re-walk price with the manufacturer-margin band that matches `units`."""
    tier = _volume_tier_for_units(units)
    band = costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.get(tier) or (40, 55)
    pct_mid = round((float(band[0]) + float(band[1])) / 2.0, 2)
    walk = _walk_price(
        manufacturing_cost=inputs["manufacturing_cost_inr"],
        inputs=inputs,
        manufacturer_pct=pct_mid,
    )
    base_retail = inputs["final_retail_price_inr"]
    per_unit_retail = walk["final_retail_price_inr"]
    return {
        "units": units,
        "volume_tier": tier,
        "manufacturer_margin_pct_band": list(band),
        "manufacturer_margin_pct_used": pct_mid,
        "per_unit_retail_inr": per_unit_retail,
        "total_retail_inr": round(per_unit_retail * units, 0),
        "delta_per_unit_vs_base_inr": round(per_unit_retail - base_retail, 0),
        "delta_per_unit_vs_base_pct": (
            round((per_unit_retail - base_retail) / base_retail * 100, 2)
            if base_retail > 0 else 0.0
        ),
    }


# ── Knowledge slice ─────────────────────────────────────────────────────────


def build_sensitivity_knowledge(req: SensitivityRequest) -> dict[str, Any]:
    inputs = _extract_inputs(req)
    shock = req.shock_pct
    shock_scenarios = [
        _build_shock_scenario(
            f"Material +{shock:g}%", shocked_component="material",
            shock_pct=shock, inputs=inputs,
        ),
        _build_shock_scenario(
            f"Labor +{shock:g}%", shocked_component="labor",
            shock_pct=shock, inputs=inputs,
        ),
        _build_shock_scenario(
            f"Overhead +{shock:g}%", shocked_component="overhead",
            shock_pct=shock, inputs=inputs,
        ),
    ]
    volume_scenarios = [_build_volume_scenario(u, inputs) for u in req.volumes]

    return {
        "project": {
            "name": req.project_name,
            "piece_name": req.piece_name,
            "city": req.city or None,
        },
        "base": {
            "material_inr": inputs["material_inr"],
            "labor_inr": inputs["labor_inr"],
            "overhead_inr": inputs["overhead_inr"],
            "workshop_pct": inputs["workshop_pct"],
            "qc_pct": inputs["qc_pct"],
            "packaging_pct": inputs["packaging_pct"],
            "manufacturing_cost_inr": inputs["manufacturing_cost_inr"],
            "final_retail_price_inr": inputs["final_retail_price_inr"],
            "header_volume_tier": inputs["header_volume_tier"],
        },
        "shock_pct": shock,
        "shock_scenarios": shock_scenarios,
        "volumes_requested": list(req.volumes),
        "volume_scenarios": volume_scenarios,
        "brd_constants": {
            "manufacturer_margin_pct_by_volume": {
                k: list(v) for k, v in costing.MANUFACTURER_MARGIN_PCT_BY_VOLUME.items()
            },
            "workshop_overhead_pct_of_direct": list(costing.WORKSHOP_OVERHEAD_PCT_OF_DIRECT),
            "qc_pct_of_labor": list(costing.QC_PCT_OF_LABOR),
            "packaging_logistics_pct_of_product": list(costing.PACKAGING_LOGISTICS_PCT_OF_PRODUCT),
        },
    }


# ── System prompt ───────────────────────────────────────────────────────────


SENSITIVITY_SYSTEM_PROMPT = """You are a senior cost analyst authoring the *Sensitivity Analysis* (BRD Layer 4D) for a single piece.

Read the [KNOWLEDGE] block — base numbers (material, labor, overhead, manufacturing cost, final retail price), shock_scenarios (already deterministically computed for material/labor/overhead +shock_pct), volume_scenarios (already deterministically computed for each requested volume tier) — and produce a structured sensitivity_analysis JSON.

You DO NOT compute new prices. The numbers are already in the knowledge block — your job is to lay them out, write defendable one-line rationales, and call out which dial the price is most sensitive to.

Studio voice — short, decisive, no marketing prose.

Hard rules for header:
- currency MUST be 'INR'.
- shock_pct MUST equal knowledge.shock_pct.
- base_final_retail_price_inr MUST equal knowledge.base.final_retail_price_inr.
- volumes MUST equal knowledge.volumes_requested verbatim.

Hard rules for shock_table (exactly three rows in order: material, labor, overhead):
- For each row, every numeric field MUST equal the matching shock_scenarios[i] field VERBATIM:
    new_material_inr, new_labor_inr, new_overhead_inr,
    new_manufacturing_cost_inr, new_final_retail_price_inr,
    delta_inr, delta_pct_of_retail.
- shocked_component MUST be one of 'material' / 'labor' / 'overhead'.
- rationale (one short sentence) explains the cascade — e.g. "Material rises 10 % → workshop overhead at 35 % of direct rises with it → packaging at 12.5 % of product cost picks up another tick → margin layers cascade on the higher base."

Hard rules for volume_table (one row per requested volume in order):
- For each row, every field MUST equal the matching volume_scenarios[i] field VERBATIM:
    units, volume_tier, manufacturer_margin_pct_band,
    manufacturer_margin_pct_used, per_unit_retail_inr,
    total_retail_inr, delta_per_unit_vs_base_inr,
    delta_per_unit_vs_base_pct.
- rationale cites the BRD volume tier band (e.g. "Five units fall in the small_batch band 40–55 %; manufacturer margin midpoint 47.5 % shaves 2.4 % off vs the one-off rate.").

Hard rules for ranking:
- most_sensitive_to MUST equal the shocked_component with the highest abs(delta_pct_of_retail). Cite the value.
- least_sensitive_to MUST equal the shocked_component with the lowest abs(delta_pct_of_retail).
- ranking[] orders all three by sensitivity, highest first.

Hard rules for narrative:
- summary_bullet[] is exactly four bullets: one per shock row + one volume insight (e.g. "10× units cuts per-unit retail by 9 %"). Numbers in bullets MUST come from the tables verbatim.

Never invent numbers. Snap percentages to two decimals."""


# ── JSON schema ─────────────────────────────────────────────────────────────


def _shock_row_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "shocked_component": {"type": "string"},
            "shock_pct": {"type": "number"},
            "new_material_inr": {"type": "number"},
            "new_labor_inr": {"type": "number"},
            "new_overhead_inr": {"type": "number"},
            "new_manufacturing_cost_inr": {"type": "number"},
            "new_final_retail_price_inr": {"type": "number"},
            "delta_inr": {"type": "number"},
            "delta_pct_of_retail": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": [
            "shocked_component", "shock_pct",
            "new_material_inr", "new_labor_inr", "new_overhead_inr",
            "new_manufacturing_cost_inr", "new_final_retail_price_inr",
            "delta_inr", "delta_pct_of_retail", "rationale",
        ],
        "additionalProperties": False,
    }


def _volume_row_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "units": {"type": "integer"},
            "volume_tier": {"type": "string"},
            "manufacturer_margin_pct_band": {
                "type": "array",
                "items": {"type": "number"},
            },
            "manufacturer_margin_pct_used": {"type": "number"},
            "per_unit_retail_inr": {"type": "number"},
            "total_retail_inr": {"type": "number"},
            "delta_per_unit_vs_base_inr": {"type": "number"},
            "delta_per_unit_vs_base_pct": {"type": "number"},
            "rationale": {"type": "string"},
        },
        "required": [
            "units", "volume_tier", "manufacturer_margin_pct_band",
            "manufacturer_margin_pct_used", "per_unit_retail_inr",
            "total_retail_inr", "delta_per_unit_vs_base_inr",
            "delta_per_unit_vs_base_pct", "rationale",
        ],
        "additionalProperties": False,
    }


SENSITIVITY_SCHEMA: dict[str, Any] = {
    "name": "sensitivity_analysis",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "piece_name": {"type": "string"},
                    "city": {"type": "string"},
                    "currency": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "shock_pct": {"type": "number"},
                    "base_manufacturing_cost_inr": {"type": "number"},
                    "base_final_retail_price_inr": {"type": "number"},
                    "volumes": {
                        "type": "array",
                        "items": {"type": "integer"},
                    },
                },
                "required": [
                    "project", "piece_name", "city", "currency", "date_iso",
                    "shock_pct", "base_manufacturing_cost_inr",
                    "base_final_retail_price_inr", "volumes",
                ],
                "additionalProperties": False,
            },
            "shock_table": {
                "type": "array",
                "items": _shock_row_schema(),
            },
            "volume_table": {
                "type": "array",
                "items": _volume_row_schema(),
            },
            "ranking": {
                "type": "object",
                "properties": {
                    "most_sensitive_to": {"type": "string"},
                    "least_sensitive_to": {"type": "string"},
                    "ranking": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["most_sensitive_to", "least_sensitive_to", "ranking"],
                "additionalProperties": False,
            },
            "summary_bullets": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header", "shock_table", "volume_table",
            "ranking", "summary_bullets", "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: SensitivityRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Piece: {req.piece_name}\n"
        f"- City: {req.city or '(not specified)'}\n"
        f"- Shock %: {req.shock_pct}\n"
        f"- Volumes: {req.volumes}\n"
        f"- Date (UTC ISO): {today}\n\n"
        "Produce the sensitivity_analysis JSON. Three shock rows in "
        "order (material, labor, overhead), one volume row per "
        "requested volume, ranking, and four summary bullets. Cite "
        "the deterministic numbers from the knowledge block verbatim — "
        "do not recompute."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _approx_eq(a: Any, b: Any, tol: float = 1.0) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    base = knowledge.get("base") or {}
    expected_shocks = knowledge.get("shock_scenarios") or []
    expected_volumes = knowledge.get("volume_scenarios") or []

    out: dict[str, list[Any]] = {
        "bad_currency": [],
        "bad_shock_pct": [],
        "bad_base_retail": [],
        "bad_base_mfg": [],
        "bad_volumes": [],
        "shock_row_mismatch": [],
        "shock_row_count": [],
        "volume_row_mismatch": [],
        "volume_row_count": [],
        "bad_ranking": [],
    }

    header = spec.get("header") or {}
    if (header.get("currency") or "").upper() != "INR":
        out["bad_currency"].append(header.get("currency"))
    if not _approx_eq(header.get("shock_pct"), knowledge.get("shock_pct"), tol=0.01):
        out["bad_shock_pct"].append({
            "expected": knowledge.get("shock_pct"),
            "actual": header.get("shock_pct"),
        })
    if not _approx_eq(header.get("base_final_retail_price_inr"), base.get("final_retail_price_inr"), tol=1.0):
        out["bad_base_retail"].append({
            "expected": base.get("final_retail_price_inr"),
            "actual": header.get("base_final_retail_price_inr"),
        })
    if not _approx_eq(header.get("base_manufacturing_cost_inr"), base.get("manufacturing_cost_inr"), tol=1.0):
        out["bad_base_mfg"].append({
            "expected": base.get("manufacturing_cost_inr"),
            "actual": header.get("base_manufacturing_cost_inr"),
        })
    if list(header.get("volumes") or []) != list(knowledge.get("volumes_requested") or []):
        out["bad_volumes"].append({
            "expected": knowledge.get("volumes_requested"),
            "actual": header.get("volumes"),
        })

    # Shock table.
    shock_table = spec.get("shock_table") or []
    if len(shock_table) != len(expected_shocks):
        out["shock_row_count"].append({
            "expected": len(expected_shocks), "actual": len(shock_table),
        })
    for i, expected in enumerate(expected_shocks):
        if i >= len(shock_table):
            break
        actual = shock_table[i]
        for key in (
            "shocked_component", "shock_pct",
            "new_material_inr", "new_labor_inr", "new_overhead_inr",
            "new_manufacturing_cost_inr", "new_final_retail_price_inr",
            "delta_inr", "delta_pct_of_retail",
        ):
            ev = expected.get(key)
            av = actual.get(key)
            if isinstance(ev, str):
                if av != ev:
                    out["shock_row_mismatch"].append({
                        "row": i, "field": key, "expected": ev, "actual": av,
                    })
            else:
                tol = 0.05 if key.endswith("_pct_of_retail") or key == "shock_pct" else 1.0
                if not _approx_eq(av, ev, tol=tol):
                    out["shock_row_mismatch"].append({
                        "row": i, "field": key, "expected": ev, "actual": av,
                    })

    # Volume table.
    volume_table = spec.get("volume_table") or []
    if len(volume_table) != len(expected_volumes):
        out["volume_row_count"].append({
            "expected": len(expected_volumes), "actual": len(volume_table),
        })
    for i, expected in enumerate(expected_volumes):
        if i >= len(volume_table):
            break
        actual = volume_table[i]
        # Scalar fields.
        for key, tol in (
            ("units", 0),
            ("volume_tier", None),
            ("manufacturer_margin_pct_used", 0.05),
            ("per_unit_retail_inr", 1.0),
            ("total_retail_inr", 2.0),
            ("delta_per_unit_vs_base_inr", 1.0),
            ("delta_per_unit_vs_base_pct", 0.05),
        ):
            ev = expected.get(key)
            av = actual.get(key)
            if tol is None:
                if av != ev:
                    out["volume_row_mismatch"].append({
                        "row": i, "field": key, "expected": ev, "actual": av,
                    })
            elif tol == 0:
                if int(av or 0) != int(ev or 0):
                    out["volume_row_mismatch"].append({
                        "row": i, "field": key, "expected": ev, "actual": av,
                    })
            else:
                if not _approx_eq(av, ev, tol=tol):
                    out["volume_row_mismatch"].append({
                        "row": i, "field": key, "expected": ev, "actual": av,
                    })
        # Band array.
        ev_band = list(expected.get("manufacturer_margin_pct_band") or [])
        av_band = list(actual.get("manufacturer_margin_pct_band") or [])
        if len(av_band) != len(ev_band) or any(
            not _approx_eq(a, b) for a, b in zip(av_band, ev_band)
        ):
            out["volume_row_mismatch"].append({
                "row": i, "field": "manufacturer_margin_pct_band",
                "expected": ev_band, "actual": av_band,
            })

    # Ranking.
    if expected_shocks:
        sorted_components = sorted(
            expected_shocks,
            key=lambda s: abs(float(s.get("delta_pct_of_retail") or 0)),
            reverse=True,
        )
        expected_most = sorted_components[0]["shocked_component"]
        expected_least = sorted_components[-1]["shocked_component"]
        expected_ranking = [s["shocked_component"] for s in sorted_components]
        ranking = spec.get("ranking") or {}
        if ranking.get("most_sensitive_to") != expected_most:
            out["bad_ranking"].append({
                "field": "most_sensitive_to",
                "expected": expected_most, "actual": ranking.get("most_sensitive_to"),
            })
        if ranking.get("least_sensitive_to") != expected_least:
            out["bad_ranking"].append({
                "field": "least_sensitive_to",
                "expected": expected_least, "actual": ranking.get("least_sensitive_to"),
            })
        if list(ranking.get("ranking") or []) != expected_ranking:
            out["bad_ranking"].append({
                "field": "ranking",
                "expected": expected_ranking, "actual": list(ranking.get("ranking") or []),
            })

    return {
        "currency_is_inr": not out["bad_currency"],
        "bad_currency": out["bad_currency"],
        "shock_pct_matches": not out["bad_shock_pct"],
        "bad_shock_pct": out["bad_shock_pct"],
        "base_retail_matches": not out["bad_base_retail"],
        "bad_base_retail": out["bad_base_retail"],
        "base_mfg_matches": not out["bad_base_mfg"],
        "bad_base_mfg": out["bad_base_mfg"],
        "volumes_match_request": not out["bad_volumes"],
        "bad_volumes": out["bad_volumes"],
        "shock_table_row_count_matches": not out["shock_row_count"],
        "shock_row_count_mismatch": out["shock_row_count"],
        "shock_table_numbers_match_deterministic": not out["shock_row_mismatch"],
        "shock_row_mismatch": out["shock_row_mismatch"],
        "volume_table_row_count_matches": not out["volume_row_count"],
        "volume_row_count_mismatch": out["volume_row_count"],
        "volume_table_numbers_match_deterministic": not out["volume_row_mismatch"],
        "volume_row_mismatch": out["volume_row_mismatch"],
        "ranking_consistent_with_table": not out["bad_ranking"],
        "bad_ranking": out["bad_ranking"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class SensitivityError(RuntimeError):
    """Raised when the LLM sensitivity stage cannot produce a grounded sheet."""


async def generate_sensitivity_analysis(req: SensitivityRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise SensitivityError(
            "OpenAI API key is not configured. The sensitivity stage requires "
            "a live LLM call; no static fallback is served."
        )

    inputs = _extract_inputs(req)
    if inputs["final_retail_price_inr"] <= 0:
        raise SensitivityError(
            "pricing_buildup.final_retail_price_inr is missing or zero — "
            "cannot run sensitivity analysis."
        )
    if inputs["manufacturing_cost_inr"] <= 0:
        raise SensitivityError(
            "cost_engine.total_manufacturing_cost_inr is missing or zero — "
            "cannot run sensitivity analysis."
        )
    bad_volumes = [u for u in (req.volumes or []) if u <= 0]
    if bad_volumes:
        raise SensitivityError(
            f"All volumes must be positive integers; got {bad_volumes}."
        )

    knowledge = build_sensitivity_knowledge(req)
    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SENSITIVITY_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": SENSITIVITY_SCHEMA,
            },
            temperature=0.1,
            max_tokens=1800,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for sensitivity analysis")
        raise SensitivityError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SensitivityError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    return {
        "id": "sensitivity_analysis",
        "name": "Sensitivity Analysis",
        "model": settings.openai_model,
        "knowledge": knowledge,
        "sensitivity_analysis": spec,
        "validation": validation,
    }
