"""Stage 10 agent tool — Design Brief intake (BRD §1A).

Wraps :func:`app.services.design_brief_service.validate_and_normalize`
so the agent can intake / validate a 5-section design brief during
chat, without the user round-tripping through the ``/brief/intake``
HTTP route.

The brief itself is pure-validation — it does NOT create a project
or persist anything. The agent typically calls this tool first
(to canonicalise the brief), then calls a separate generation tool
that turns the brief into a design graph.

Two tools ship:

- :func:`intake_design_brief` — validate + normalise + return
  warnings list. Read-only (no audit).
- :func:`brief_to_context` — flatten a normalised brief into the
  generation-pipeline context dict.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.models.brief import DesignBriefIn, DesignBriefOut
from app.services.design_brief_service import (
    brief_to_generation_context,
    validate_and_normalize,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# 1. intake_design_brief
# ─────────────────────────────────────────────────────────────────────


class IntakeDesignBriefInput(BaseModel):
    """The full 5-section BRD §1A design brief.

    Field shapes mirror :class:`app.models.brief.DesignBriefIn` 1:1
    so the agent's JSON output can be passed through unchanged.
    """

    project_type: dict[str, Any] = Field(
        description=(
            "Section 1 — {type, sub_type, scale}. type ∈ "
            "{residential, commercial, hospitality, institutional, "
            "retail, office, mixed_use, industrial, custom}."
        ),
    )
    theme: dict[str, Any] = Field(
        description=(
            "Section 2 — {theme, custom_spec}. theme ∈ {pedestal, "
            "contemporary, modern, mid_century_modern, custom}. "
            "If theme=custom, custom_spec is required."
        ),
    )
    space: dict[str, Any] = Field(
        description=(
            "Section 3 — {dimensions: {length, width, height?, unit}, "
            "constraints: [...], site_conditions: {orientation, "
            "floor_level, access, existing_features, natural_light, "
            "ventilation, noise_context}}. unit ∈ {m, ft}."
        ),
    )
    requirements: dict[str, Any] = Field(
        description=(
            "Section 4 — {functional_needs, aesthetic_preferences, "
            "narrative, budget, currency, timeline_weeks}. At least "
            "one of functional_needs / aesthetic_preferences / "
            "narrative is required."
        ),
    )
    regulatory: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Section 5 (optional) — {country, state, city, "
            "postal_code, building_codes, climatic_zone, "
            "compliance_notes}. Defaulted from city if omitted."
        ),
    )
    notes: str = Field(
        default="",
        max_length=5000,
        description="Free-form architect notes attached to the brief.",
    )


class IntakeDesignBriefOutput(BaseModel):
    brief_id: str
    status: str
    project_type: dict[str, Any]
    theme: dict[str, Any]
    space: dict[str, Any]
    requirements: dict[str, Any]
    regulatory: dict[str, Any]
    warnings: list[str] = Field(default_factory=list)
    """Defaulted-field notices, code-pack inferences, low-budget
    flags, theme-not-known fallbacks. Surface to the user — these
    are non-fatal but they tell them what the system filled in."""


def _brief_out_to_payload(out: DesignBriefOut) -> dict[str, Any]:
    """Convert pydantic model → JSON-safe dict (enums → strings)."""
    return {
        "brief_id": out.brief_id,
        "status": out.status,
        "project_type": out.project_type.model_dump(mode="json"),
        "theme": out.theme.model_dump(mode="json"),
        "space": out.space.model_dump(mode="json"),
        "requirements": out.requirements.model_dump(mode="json"),
        "regulatory": out.regulatory.model_dump(mode="json"),
        "warnings": list(out.warnings),
    }


@tool(
    name="intake_design_brief",
    description=(
        "Validate and normalise a 5-section design brief per BRD §1A. "
        "Sections: project_type, theme, space, requirements, "
        "regulatory. Returns the canonicalised brief with a brief_id "
        "and a list of warnings (defaulted fields, theme not in "
        "rule pack, low-budget flags, climatic zone inferred from "
        "city). Read-only — does NOT create a project. Call this "
        "first to canonicalise, then chain into a generation tool. "
        "Theme aliases (mcm / midcentury → mid_century_modern; "
        "plinth → pedestal) resolve automatically."
    ),
    timeout_seconds=15.0,
)
async def intake_design_brief(
    ctx: ToolContext,
    input: IntakeDesignBriefInput,
) -> IntakeDesignBriefOutput:
    try:
        payload = DesignBriefIn.model_validate({
            "project_type": dict(input.project_type or {}),
            "theme": dict(input.theme or {}),
            "space": dict(input.space or {}),
            "requirements": dict(input.requirements or {}),
            "regulatory": dict(input.regulatory or {}),
            "notes": input.notes or "",
        })
    except Exception as exc:  # noqa: BLE001 — Pydantic raises a chain
        raise ToolError(f"Invalid brief: {exc}") from exc

    try:
        out = validate_and_normalize(payload)
    except ValueError as exc:
        raise ToolError(f"Brief rejected: {exc}") from exc

    return IntakeDesignBriefOutput(**_brief_out_to_payload(out))


# ─────────────────────────────────────────────────────────────────────
# 2. brief_to_context
# ─────────────────────────────────────────────────────────────────────


class BriefToContextInput(BaseModel):
    """Same shape as :class:`IntakeDesignBriefInput` — we re-validate
    so the tool is idempotent and self-contained."""

    project_type: dict[str, Any]
    theme: dict[str, Any]
    space: dict[str, Any]
    requirements: dict[str, Any]
    regulatory: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=5000)


class BriefToContextOutput(BaseModel):
    brief_id: str
    warnings: list[str] = Field(default_factory=list)
    context: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Flattened generation-pipeline context — the dict the "
            "design pipeline consumes downstream."
        ),
    )


@tool(
    name="brief_to_generation_context",
    description=(
        "Convert a 5-section design brief into the flat "
        "generation-pipeline context dict (project_type / theme / "
        "dimensions / functional_needs / regulatory.* / etc.). "
        "Use after intake_design_brief when chaining into the "
        "design generation pipeline. Read-only."
    ),
    timeout_seconds=15.0,
)
async def brief_to_generation_context_tool(
    ctx: ToolContext,
    input: BriefToContextInput,
) -> BriefToContextOutput:
    try:
        payload = DesignBriefIn.model_validate({
            "project_type": dict(input.project_type or {}),
            "theme": dict(input.theme or {}),
            "space": dict(input.space or {}),
            "requirements": dict(input.requirements or {}),
            "regulatory": dict(input.regulatory or {}),
            "notes": input.notes or "",
        })
    except Exception as exc:  # noqa: BLE001
        raise ToolError(f"Invalid brief: {exc}") from exc

    try:
        normalised = validate_and_normalize(payload)
    except ValueError as exc:
        raise ToolError(f"Brief rejected: {exc}") from exc

    return BriefToContextOutput(
        brief_id=normalised.brief_id,
        warnings=list(normalised.warnings),
        context=brief_to_generation_context(normalised),
    )
