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
from app.models.brief import BriefThemeEnum, DesignBriefIn, DesignBriefOut
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


# ─────────────────────────────────────────────────────────────────────
# 3. extract_brief_from_notes — completeness check over a partial brief
# ─────────────────────────────────────────────────────────────────────


class ExtractBriefFromNotesInput(BaseModel):
    """A partial 5-section design brief — every section optional.

    The agent (or the chat layer) builds this up turn-by-turn from the
    user's natural-language statements and the notes sidebar. This tool
    is the deterministic completeness checker: it reports which sections
    are confirmed vs. partial vs. pending, lists the missing fields, and
    — when every section is confirmed — produces the canonical brief by
    delegating to :func:`validate_and_normalize`.
    """

    project_type: Optional[dict[str, Any]] = Field(
        default=None,
        description="Section 1 (optional). {type, sub_type, scale}",
    )
    theme: Optional[dict[str, Any]] = Field(
        default=None,
        description="Section 2 (optional). {theme, custom_spec}",
    )
    space: Optional[dict[str, Any]] = Field(
        default=None,
        description="Section 3 (optional). {dimensions, constraints, site_conditions}",
    )
    requirements: Optional[dict[str, Any]] = Field(
        default=None,
        description="Section 4 (optional). {functional_needs, aesthetic_preferences, narrative, budget, currency, timeline_weeks}",
    )
    regulatory: Optional[dict[str, Any]] = Field(
        default=None,
        description="Section 5 (optional). {country, state, city, postal_code, building_codes, climatic_zone, compliance_notes}",
    )
    notes: str = Field(default="", max_length=5000)


class ExtractBriefFromNotesOutput(BaseModel):
    status: dict[str, str] = Field(
        description="One of pending / partial / confirmed per section.",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Dotted paths still needed to reach all-confirmed.",
    )
    ready_to_design: bool = Field(
        description="True when all 5 sections are confirmed and the brief validates.",
    )
    partial_brief: dict[str, Any] = Field(
        default_factory=dict,
        description="The brief as captured so far — echoed back for the sidebar.",
    )
    canonical_brief: Optional[dict[str, Any]] = Field(
        default=None,
        description="The validated DesignBriefOut. Present only when ready_to_design.",
    )
    warnings: list[str] = Field(default_factory=list)


# Map of dotted-path → "section.field" used to surface missing fields.
_SECTIONS = ("project_type", "theme", "space", "requirements", "regulatory")


def _check_project_type(data: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not data:
        return "pending", ["project_type.type"]
    if data.get("type"):
        return "confirmed", []
    return "partial", ["project_type.type"]


def _check_theme(data: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not data:
        return "pending", ["theme.theme"]
    theme = (data.get("theme") or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not theme:
        return "partial", ["theme.theme"]
    if theme == BriefThemeEnum.CUSTOM.value and not (data.get("custom_spec") or "").strip():
        return "partial", ["theme.custom_spec"]
    return "confirmed", []


def _check_space(data: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not data:
        return "pending", [
            "space.dimensions.length",
            "space.dimensions.width",
            "space.dimensions.unit",
        ]
    dims = data.get("dimensions") or {}
    missing: list[str] = []
    if not dims.get("length"):
        missing.append("space.dimensions.length")
    if not dims.get("width"):
        missing.append("space.dimensions.width")
    if not dims.get("unit"):
        missing.append("space.dimensions.unit")
    if not missing:
        return "confirmed", []
    if len(missing) == 3:
        return "pending", missing
    return "partial", missing


def _check_requirements(data: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not data:
        return "pending", ["requirements.functional_needs|aesthetic_preferences|narrative"]
    has_signal = (
        bool(data.get("functional_needs"))
        or bool(data.get("aesthetic_preferences"))
        or bool((data.get("narrative") or "").strip())
    )
    if has_signal:
        return "confirmed", []
    return "partial", ["requirements.functional_needs|aesthetic_preferences|narrative"]


def _check_regulatory(data: dict[str, Any] | None) -> tuple[str, list[str]]:
    if not data:
        return "pending", ["regulatory.country|city"]
    if (data.get("country") or "").strip() or (data.get("city") or "").strip():
        return "confirmed", []
    return "partial", ["regulatory.country|city"]


_SECTION_CHECKERS = {
    "project_type": _check_project_type,
    "theme": _check_theme,
    "space": _check_space,
    "requirements": _check_requirements,
    "regulatory": _check_regulatory,
}


@tool(
    name="extract_brief_from_notes",
    description=(
        "Deterministic completeness check over a partial 5-section "
        "design brief (BRD §1A). Pass whatever has been captured so "
        "far from the conversation / notes sidebar; the tool returns "
        "a per-section status (pending / partial / confirmed), the "
        "list of dotted-path fields still missing, and — when every "
        "section is confirmed — a canonical, validated brief via "
        "validate_and_normalize. Use this to drive the 'Ready to "
        "design' affordance and to know what to ask the user next."
    ),
    timeout_seconds=15.0,
)
async def extract_brief_from_notes(
    ctx: ToolContext,
    input: ExtractBriefFromNotesInput,
) -> ExtractBriefFromNotesOutput:
    partial: dict[str, Any] = {
        "project_type": dict(input.project_type or {}) or None,
        "theme": dict(input.theme or {}) or None,
        "space": dict(input.space or {}) or None,
        "requirements": dict(input.requirements or {}) or None,
        "regulatory": dict(input.regulatory or {}) or None,
    }
    if input.notes:
        partial["notes"] = input.notes

    status: dict[str, str] = {}
    missing_fields: list[str] = []
    for section in _SECTIONS:
        section_status, section_missing = _SECTION_CHECKERS[section](partial.get(section))
        status[section] = section_status
        missing_fields.extend(section_missing)

    ready = all(state == "confirmed" for state in status.values())

    canonical: dict[str, Any] | None = None
    warnings: list[str] = []
    if ready:
        # Promote partial → strict DesignBriefIn and run cross-field checks.
        try:
            full_payload = DesignBriefIn.model_validate({
                "project_type": partial["project_type"] or {},
                "theme": partial["theme"] or {},
                "space": partial["space"] or {},
                "requirements": partial["requirements"] or {},
                "regulatory": partial["regulatory"] or {},
                "notes": input.notes or "",
            })
            normalised = validate_and_normalize(full_payload)
        except Exception as exc:  # noqa: BLE001 — Pydantic chain or ValueError
            # Section-level checks said "confirmed" but stricter validation
            # rejected — surface as a soft failure rather than crashing.
            ready = False
            warnings.append(f"Section checks passed but full validation failed: {exc}")
        else:
            canonical = _brief_out_to_payload(normalised)
            warnings = list(normalised.warnings)

    return ExtractBriefFromNotesOutput(
        status=status,
        missing_fields=missing_fields,
        ready_to_design=ready,
        partial_brief={k: v for k, v in partial.items() if v not in (None, {})},
        canonical_brief=canonical,
        warnings=warnings,
    )
