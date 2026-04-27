"""LLM-driven Design Process diagram (BRD Layer 2B #5).

The narrative sheet — a step-by-step design log explaining what was
decided, where the decision points sat, and which rule (theme,
ergonomic, code, cost) drove each choice. This is the page a project
architect would hand a junior to onboard them onto a project.

Pipeline contract (same as the other 2B services):

    INPUT (theme + design graph + parametric_spec + architect_brief)
      → INJECT  (theme rule pack + decision-stage catalogue +
                 rule-driver vocabulary + graph step log)
      → LLM CALL  (live OpenAI; no static fallback)
      → RENDER  (deterministic vertical-flow base + LLM step annotations)
      → OUTPUT  (design_process_spec JSON + annotated SVG)

The four BRD requirements:
  • Step-by-step design narrative
  • Decision points documented
  • Why each choice was made
  • Generated from design log + rule extraction
"""

from __future__ import annotations

import html
import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import themes
from app.services.diagrams import design_process
from app.services.diagrams.svg_base import (
    ACCENT_COOL,
    ACCENT_WARM,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER_DEEP,
    rect,
    text,
)

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


# ── Catalogues that bound LLM choices ───────────────────────────────────────
DECISION_STAGES = (
    "brief_capture",         # raw inputs received
    "theme_selection",       # which preset / custom path
    "site_response",         # climate, regulatory, orientation
    "zoning",                # functional zone split
    "form_development",      # mass + grid + articulation
    "material_palette",      # species, finishes, hardware
    "ergonomic_resolution",  # seat heights, clearances, etc.
    "structural_resolution", # column / span / load decisions
    "mep_strategy",          # HVAC / electrical / plumbing
    "cost_envelope",         # margin / segment / pricing walk
    "production_handoff",    # joinery / tolerances / lead time
    "validation_pass",       # knowledge validator round
)

RULE_DRIVERS = (
    "theme_rule_pack",       # signature moves, palette
    "ergonomic_envelope",    # BRD 1C / Neufert ranges
    "building_code",         # NBC / ECBC / IBC / IECC
    "climate_response",      # zone-specific passive strategy
    "structural_logic",      # IS-875 / IS-456 / spans
    "mep_standard",          # ASHRAE / NBC Pt 9 / IS-732
    "manufacturing_constraint",  # tolerances, joinery, MOQ
    "cost_envelope",         # BRD costing bands
    "client_brief",          # explicit client requirement
    "regional_availability", # local material market
)


# ── Request schema ──────────────────────────────────────────────────────────


class DesignProcessRequest(BaseModel):
    theme: str = Field(min_length=2, max_length=64)
    design_graph: dict[str, Any] | None = None
    parametric_spec: dict[str, Any] | None = None
    architect_brief: dict[str, Any] | None = None
    project_summary: str = Field(default="", max_length=2000)
    canvas_width: int = Field(default=900, ge=400, le=2400)
    canvas_height: int = Field(default=720, ge=320, le=2200)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _extract_existing_steps(graph: dict[str, Any]) -> list[dict[str, str]]:
    """Pull the deterministic step log out of the existing renderer.

    Reused so the LLM sees what was already captured and can extend
    rather than duplicate.
    """
    raw = design_process._build_steps(graph)
    return [{"label": l, "detail": d, "category": c} for (l, d, c) in raw]


def build_process_knowledge(req: DesignProcessRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) or {}
    graph = req.design_graph or {}
    return {
        "theme_rule_pack": {
            "display_name": pack.get("display_name") or req.theme,
            "signature_moves": pack.get("signature_moves", []),
            "dos": pack.get("dos", []),
            "donts": pack.get("donts", []),
        },
        "decision_stages_in_scope": list(DECISION_STAGES),
        "rule_drivers_in_scope": list(RULE_DRIVERS),
        "captured_step_log": _extract_existing_steps(graph),
        "graph_summary": {
            "object_count": len(graph.get("objects", [])),
            "constraints_attached": [c.get("type") for c in graph.get("constraints", []) or []],
            "room": graph.get("room") or (graph.get("spaces") or [{}])[0],
        },
        "parametric_spec_summary": _spec_summary(req.parametric_spec or {}),
        "architect_brief_summary": _brief_summary(req.architect_brief or {}),
    }


def _spec_summary(spec: dict[str, Any]) -> dict[str, Any]:
    if not spec:
        return {}
    return {
        "primary_material": (spec.get("wood_spec") or {}).get("primary_species"),
        "hardware_style": (spec.get("hardware_spec") or {}).get("style"),
        "key_proportions": spec.get("proportions", {}).get("key_ratios", []),
        "ergonomic_targets": spec.get("ergonomic_targets", []),
        "geometry": spec.get("geometry", {}),
    }


def _brief_summary(brief: dict[str, Any]) -> dict[str, Any]:
    if not brief:
        return {}
    return {
        "project_summary": brief.get("project_summary"),
        "site_and_context": brief.get("site_and_context"),
        "structural_strategy": brief.get("structural_strategy"),
        "mep_strategy": brief.get("mep_strategy"),
        "code_compliance_count": len(brief.get("code_compliance", []) or []),
        "risks_count": len(brief.get("risks_and_watchouts", []) or []),
    }


# ── System prompt + JSON schema ─────────────────────────────────────────────


PROCESS_AUTHOR_SYSTEM_PROMPT = """You are the project architect writing the *design process* page for a project drawing set. You are documenting how the project moved from brief to spec — every meaningful decision, the rule that drove it, and the alternative you rejected.

Read the [KNOWLEDGE] block — captured step log (deterministic), parametric spec summary, architect-brief summary, theme rule pack — and synthesise a structured process narrative.

Hard rules:
- Each step.stage MUST be a key in decision_stages_in_scope.
- Each step.driven_by MUST be one of rule_drivers_in_scope.
- Build on the captured_step_log; do not contradict it. Add the *why* the deterministic log can't see.
- Each step is one decisive sentence + a short rationale + (where relevant) the rejected_alternative.
- If a stage in the catalogue genuinely doesn't apply to this project, omit it — don't fake it.
- Cite real numbers from the spec / brief summary when available.
- Studio voice — short, technical, decisive."""


PROCESS_DIAGRAM_SCHEMA: dict[str, Any] = {
    "name": "design_process_spec",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "narrative_summary": {
                "type": "string",
                "description": "Two sentences: how this project arrived at its current state.",
            },
            "steps": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {"type": "integer"},
                        "stage": {"type": "string"},
                        "title": {"type": "string"},
                        "decision": {"type": "string"},
                        "driven_by": {"type": "string"},
                        "rationale": {"type": "string"},
                        "rejected_alternative": {"type": "string"},
                    },
                    "required": [
                        "index",
                        "stage",
                        "title",
                        "decision",
                        "driven_by",
                        "rationale",
                        "rejected_alternative",
                    ],
                    "additionalProperties": False,
                },
            },
            "key_decision_points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    "required": ["title", "summary"],
                    "additionalProperties": False,
                },
            },
            "rules_invoked": {
                "type": "array",
                "items": {"type": "string"},
            },
            "open_questions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "narrative_summary",
            "steps",
            "key_decision_points",
            "rules_invoked",
            "open_questions",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: DesignProcessRequest, knowledge: dict[str, Any]) -> str:
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Theme: {req.theme}\n"
        f"- Project summary: {req.project_summary or '(none supplied)'}\n\n"
        "Write the design_process_spec JSON. Anchor on the captured_step_log, "
        "extend it with the why behind each move, and surface the genuinely-tough "
        "decision points separately. Use only known stages and known rule drivers."
    )


# ── SVG annotation overlay ──────────────────────────────────────────────────


def _annotate_svg(
    base_svg: str,
    spec: dict[str, Any],
    canvas_w: int,
    canvas_h: int,
) -> str:
    summary = (spec.get("narrative_summary") or "").strip()
    decisions = spec.get("key_decision_points") or []
    rules = spec.get("rules_invoked") or []
    open_qs = spec.get("open_questions") or []

    overlay_parts: list[str] = []

    # Top caption — narrative summary.
    if summary:
        overlay_parts.append(rect(40, 86, canvas_w - 80, 32, fill=PAPER_DEEP, stroke="none", opacity=0.65))
        overlay_parts.append(text(52, 106, "Process: " + _wrap(summary, 110), size=11, fill=INK))

    # Right rail — key decision points.
    rail_w = 240
    rail_x = canvas_w - rail_w - 8
    rail_y = 130
    rail_h = max(160, 60 + 30 * (len(decisions) + 1) + 14 * len(open_qs))
    overlay_parts.append(rect(rail_x, rail_y, rail_w, rail_h, fill="white", stroke=INK_SOFT, stroke_width=0.6, opacity=0.92))

    cursor_y = rail_y + 18
    overlay_parts.append(text(rail_x + 12, cursor_y, "Key decision points", size=11, fill=INK, weight="600"))
    cursor_y += 16
    for d in decisions[:6]:
        overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill=ACCENT_WARM, stroke="none"))
        overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(d.get("title") or "", 30), size=10, fill=INK, weight="600"))
        cursor_y += 12
        overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(d.get("summary") or "", 32), size=9, fill=INK_SOFT))
        cursor_y += 16

    if open_qs:
        cursor_y += 6
        overlay_parts.append(text(rail_x + 12, cursor_y, "Open questions", size=11, fill=INK, weight="600"))
        cursor_y += 14
        for q in open_qs[:5]:
            overlay_parts.append(rect(rail_x + 12, cursor_y - 8, 8, 8, fill=ACCENT_COOL, stroke="none"))
            overlay_parts.append(text(rail_x + 26, cursor_y, _wrap(q, 30), size=9, fill=INK_SOFT))
            cursor_y += 12

    # Footer — rules invoked.
    if rules:
        overlay_parts.append(text(40, canvas_h - 14, "Rules invoked: " + _wrap(", ".join(rules), 130), size=10, fill=INK_MUTED))

    if not overlay_parts:
        return base_svg

    overlay = "".join(overlay_parts)
    return base_svg.replace("</svg>", overlay + "</svg>")


def _wrap(s: str, width: int) -> str:
    s = html.escape(s)
    return s if len(s) <= width else s[: width - 1] + "…"


# ── Public API ──────────────────────────────────────────────────────────────


class DesignProcessError(RuntimeError):
    """Raised when the LLM design-process stage cannot produce a grounded spec."""


async def generate_design_process_diagram(req: DesignProcessRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise DesignProcessError(
            "OpenAI API key is not configured. The design-process stage requires "
            "a live LLM call; no static fallback is served."
        )

    knowledge = build_process_knowledge(req)
    if not knowledge["theme_rule_pack"].get("display_name"):
        raise DesignProcessError(
            f"Unknown theme '{req.theme}'. No theme rule pack to ground the diagram."
        )

    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": PROCESS_AUTHOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": PROCESS_DIAGRAM_SCHEMA,
            },
            temperature=0.4,
            max_tokens=2200,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for design-process diagram")
        raise DesignProcessError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DesignProcessError("LLM returned malformed JSON") from exc

    # Validation — bounded vocabularies.
    bad_stages = [s.get("stage") for s in (spec.get("steps") or []) if s.get("stage") not in DECISION_STAGES]
    bad_drivers = [s.get("driven_by") for s in (spec.get("steps") or []) if s.get("driven_by") not in RULE_DRIVERS]
    bad_rules = [r for r in (spec.get("rules_invoked") or []) if r not in RULE_DRIVERS]
    validation = {
        "stages_valid": not bad_stages,
        "bad_stages": bad_stages,
        "drivers_valid": not bad_drivers,
        "bad_drivers": bad_drivers,
        "rules_invoked_valid": not bad_rules,
        "bad_rules_invoked": bad_rules,
    }

    base = design_process.generate(
        req.design_graph or _stub_graph(req),
        canvas_w=req.canvas_width,
        canvas_h=req.canvas_height,
    )
    annotated_svg = _annotate_svg(base["svg"], spec, req.canvas_width, base.get("meta", {}).get("height", req.canvas_height))

    return {
        "id": "design_process",
        "name": "Design Process",
        "format": "svg",
        "model": settings.openai_model,
        "theme": req.theme,
        "knowledge": knowledge,
        "design_process_spec": spec,
        "svg": annotated_svg,
        "validation": validation,
        "meta": {
            **base.get("meta", {}),
            "annotated": True,
            "step_count": len(spec.get("steps", [])),
            "decision_point_count": len(spec.get("key_decision_points", [])),
            "open_question_count": len(spec.get("open_questions", [])),
        },
    }


def _stub_graph(req: DesignProcessRequest) -> dict[str, Any]:
    geom = (req.parametric_spec or {}).get("geometry") or {}
    length_m = max(2.0, (geom.get("overall_length_mm") or 4000) / 1000.0)
    width_m = max(2.0, (geom.get("overall_width_mm") or 3000) / 1000.0)
    height_m = max(2.4, (geom.get("overall_height_mm") or 2700) / 1000.0)
    return {
        "room": {"type": "lounge", "dimensions": {"length": length_m, "width": width_m, "height": height_m}},
        "style": {"primary": (themes.get(req.theme) or {}).get("display_name") or req.theme},
        "objects": [],
        "constraints": [],
    }
