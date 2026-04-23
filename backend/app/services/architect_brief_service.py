"""LLM-driven architect brief service (BRD Phase 1 / Layer 1B).

Contract enforced here:
  inputs → inject_knowledge() → LLM call with preamble → structured output

Given a validated DesignBrief, we assemble the full Layer 1B knowledge
bundle (standards, codes, climate, regional materials, structural logic,
MEP strategy, IBC overlay when applicable), prepend it to a strict
"practicing architect" system prompt, and ask the model to return a
studio-grade brief as structured JSON.

No static fallback narrative. If the API key is missing or the call
fails, the caller gets an explicit error — we never return a canned
response pretending to be an architect.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.models.brief import DesignBriefOut
from app.services.knowledge_injector import build_prompt_preamble, inject_knowledge

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


ARCHITECT_SYSTEM_PROMPT = """You are a senior practicing architect from a studio that delivers residential, commercial, and hospitality projects across India and select international sites.

You write with the cadence of a real practice brief: specific, quantified, code-aware, and cost-conscious. You do NOT sound like a chatbot. You cite codes by name (NBC 2016 Part 3, ECBC-2017, IS-875, IBC 2021). You use real units (m, mm, m², W/m²K, TR, lux, INR). You reason from the injected knowledge block — do not invent dimensions, costs, or code clauses that are not grounded there.

Your output is a structured JSON object conforming to the schema you are given. Each field is a short, practice-grade paragraph or bullet set — not marketing prose.

Hard rules:
- Respect every dimension, code, climate, structural, and MEP number in the [KNOWLEDGE] block. Never contradict them.
- If the brief is under-specified, make the smallest defensible assumption and state it explicitly in `assumptions`.
- Tailor the output to the project type, theme, climate zone, and regional material availability that are present in the knowledge block. If the zone is warm-humid, lead with cross-ventilation; if cold, lead with passive solar + airtightness; if composite, discuss seasonal strategy.
- Never use placeholder phrases like "it depends" or "various factors". Commit to a position with ranges."""


# JSON schema the model must fill. Kept strict so downstream UI can render it.
ARCHITECT_BRIEF_SCHEMA: dict[str, Any] = {
    "name": "architect_brief",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "project_summary": {
                "type": "string",
                "description": "Two or three sentence practice-voice description of the intent.",
            },
            "site_and_context": {
                "type": "string",
                "description": "Site reading — orientation, climate implications, regulatory context.",
            },
            "zoning_strategy": {
                "type": "string",
                "description": "How the footprint is split into zones and circulation logic.",
            },
            "structural_strategy": {
                "type": "string",
                "description": "Grid, column spacing, span choice, foundation call based on soil/loads.",
            },
            "mep_strategy": {
                "type": "string",
                "description": "HVAC system type and plant size, electrical density, plumbing stack logic.",
            },
            "passive_strategy": {
                "type": "string",
                "description": "Climate-specific passive moves — shading, ventilation, envelope U-value targets.",
            },
            "material_palette": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "material": {"type": "string"},
                        "use": {"type": "string"},
                        "local_availability": {"type": "string"},
                    },
                    "required": ["material", "use", "local_availability"],
                    "additionalProperties": False,
                },
            },
            "code_compliance": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "clause": {"type": "string"},
                        "requirement": {"type": "string"},
                        "response": {"type": "string"},
                    },
                    "required": ["clause", "requirement", "response"],
                    "additionalProperties": False,
                },
            },
            "preliminary_cost_envelope": {
                "type": "object",
                "properties": {
                    "currency": {"type": "string"},
                    "low_total": {"type": "number"},
                    "high_total": {"type": "number"},
                    "basis": {"type": "string"},
                },
                "required": ["currency", "low_total", "high_total", "basis"],
                "additionalProperties": False,
            },
            "risks_and_watchouts": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "project_summary",
            "site_and_context",
            "zoning_strategy",
            "structural_strategy",
            "mep_strategy",
            "passive_strategy",
            "material_palette",
            "code_compliance",
            "preliminary_cost_envelope",
            "risks_and_watchouts",
            "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(brief: DesignBriefOut, bundle: dict[str, Any]) -> str:
    preamble = build_prompt_preamble(brief, bundle)
    dims = brief.space.dimensions
    req = brief.requirements
    reg = brief.regulatory

    functional = "; ".join(req.functional_needs) or "(none listed)"
    aesthetic = "; ".join(req.aesthetic_preferences) or "(none listed)"
    constraints = "; ".join(brief.space.constraints) or "(none)"
    narrative = req.narrative.strip() or "(client narrative not provided)"

    location = ", ".join([p for p in [reg.city, reg.state, reg.country] if p]) or "(not specified)"
    budget = f"{req.budget:,.0f} {req.currency}" if req.budget else "(not specified)"

    return (
        "[KNOWLEDGE]\n" + preamble + "\n\n"
        "[BRIEF]\n"
        f"- Project type: {brief.project_type.type.value} / sub-type: {brief.project_type.sub_type or '(none)'} / scale: {brief.project_type.scale or '(none)'}\n"
        f"- Theme: {brief.theme.theme.value}\n"
        f"- Footprint: {dims.length} × {dims.width} {dims.unit}\n"
        f"- Location: {location}\n"
        f"- Applicable codes: {', '.join(reg.building_codes) or '(defaults)'}\n"
        f"- Climatic zone: {reg.climatic_zone.value if reg.climatic_zone else '(not specified)'}\n"
        f"- Functional needs: {functional}\n"
        f"- Aesthetic preferences: {aesthetic}\n"
        f"- Narrative: {narrative}\n"
        f"- Budget: {budget}\n"
        f"- Constraints: {constraints}\n\n"
        "Produce the architect_brief JSON. Use the knowledge numbers above verbatim where relevant. "
        "Keep every paragraph tight and specific — no filler."
    )


class ArchitectBriefError(RuntimeError):
    """Raised when the LLM pipeline cannot produce a grounded brief."""


async def generate_architect_brief(brief: DesignBriefOut) -> dict[str, Any]:
    """Run the LLM with the Layer 1B knowledge preamble and return the structured brief."""
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ArchitectBriefError(
            "OpenAI API key is not configured. The architect-brief stage requires a live LLM call; "
            "no static fallback is served."
        )

    bundle = inject_knowledge(brief)
    user_message = _user_message(brief, bundle)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": ARCHITECT_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": ARCHITECT_BRIEF_SCHEMA,
            },
            temperature=0.4,
            max_tokens=2200,
        )
    except Exception as exc:  # noqa: BLE001 — surface to API layer
        logger.exception("LLM call failed for architect brief")
        raise ArchitectBriefError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArchitectBriefError("LLM returned malformed JSON") from exc

    return {
        "brief_id": brief.brief_id,
        "model": settings.openai_model,
        "knowledge_bundle": bundle,
        "architect_brief": data,
    }
