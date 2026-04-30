"""Stage 4D — spec-generation tools (BRD Layers 3B / 3C / 3D).

Three LLM-heavy tools that wrap the existing spec services so the
agent can author full technical specs as part of a chat turn:

- :func:`generate_material_spec` (BRD 3B) — palette → species →
  finish → hardware → upholstery → cost summary, all grounded in
  the theme rule pack + materials KB.
- :func:`generate_manufacturing_spec` (BRD 3C) — woodworking,
  metal fab, upholstery, QA gates, lead time, MOQ.
- :func:`generate_mep_spec` (BRD 3D) — HVAC sizing, electrical
  panels, plumbing fixtures + DFU + drain size, indicative cost.

Each tool:

1. Validates LLM input via Pydantic.
2. Builds the matching service ``*Request`` model.
3. Calls the existing service generator (one OpenAI round-trip).
4. Translates ``*SpecError`` into :class:`ToolError` so the agent
   gets a structured error envelope.
5. Returns the *full* structured sheet plus a compact summary
   the LLM can act on without re-reading the whole document.

Why these wrap pre-existing services
------------------------------------
The spec services (``app.services.material_spec_service``, etc.)
were authored in BRD 3B–3D. The tools layer here is *thin*: it
exists to make those services callable from the agent loop with
LLM-friendly input descriptions and structured error envelopes.
No business logic moves — the prompts, knowledge build, and
validation all stay where they were.

Cost guardrails
---------------
Every call hits the LLM. Per-tool timeout is 90 s (well above the
typical 30-45 s response). The tools have no built-in rate limit;
the agent loop trims runaway sessions, and routes can layer per-user
caps if needed.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.services.manufacturing_spec_service import (
    ManufacturingSpecError,
    ManufacturingSpecRequest,
    generate_manufacturing_spec as _generate_manufacturing_spec,
)
from app.services.material_spec_service import (
    MaterialSpecError,
    MaterialSpecRequest,
    generate_material_spec_sheet as _generate_material_spec_sheet,
)
from app.services.mep_spec_service import (
    MEPSpecError,
    MEPSpecRequest,
    RoomDimensions,
    generate_mep_spec as _generate_mep_spec,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────


# Default sections for each spec — match the service defaults so we
# don't double-source the truth.
_DEFAULT_MATERIAL_SECTIONS = [
    "primary_structure", "secondary_materials", "hardware",
    "upholstery", "finishing", "cost_summary",
]
_DEFAULT_MANUFACTURING_SECTIONS = [
    "woodworking_notes", "metal_fabrication_notes",
    "upholstery_assembly_notes", "quality_assurance",
]
_DEFAULT_MEP_SECTIONS = ["hvac", "electrical", "plumbing", "cost"]


def _summarise_validation(validation: Optional[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Return (overall_passed, list_of_failed_check_keys).

    Validation dicts in the spec services use boolean flags like
    ``"palette_consistent": True`` plus parallel ``"<flag>_issues":
    [...]`` lists. We treat any check whose value is explicitly
    ``False`` as a failure; non-boolean keys (the per-issue lists)
    are skipped.
    """
    if not validation:
        return True, []
    failed: list[str] = []
    for key, value in validation.items():
        if isinstance(value, bool) and value is False:
            failed.append(key)
    return (len(failed) == 0), failed


# ─────────────────────────────────────────────────────────────────────
# 1. generate_material_spec  — BRD 3B
# ─────────────────────────────────────────────────────────────────────


class GenerateMaterialSpecInput(BaseModel):
    """LLM input for the material-spec tool."""

    theme: str = Field(
        description=(
            "Theme slug — modern | mid_century_modern | pedestal | "
            "contemporary | scandinavian | rustic | industrial | "
            "minimalist | traditional | luxe. Required: every material "
            "decision is grounded in the theme's palette."
        ),
        min_length=2,
        max_length=64,
    )
    project_name: str = Field(default="KATHA Project", max_length=200)
    city: str = Field(
        default="",
        description=(
            "City or city slug — drives regional availability + the "
            "city_price_index in the cost summary."
        ),
        max_length=80,
    )
    parametric_spec: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional parametric spec (Stage 3A geometry output). When "
            "present, the LLM uses primary_species / secondary_species / "
            "finish / hardware_material to lock the spec sheet."
        ),
    )
    sections: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_MATERIAL_SECTIONS),
        description=(
            "Subset of sections to author. Default is all six: "
            "primary_structure, secondary_materials, hardware, "
            "upholstery, finishing, cost_summary."
        ),
    )


class MaterialSpecOutput(BaseModel):
    id: str
    name: str
    theme: str
    city: Optional[str] = None
    validation_passed: bool
    validation_failures: list[str] = Field(
        default_factory=list,
        description="Names of validation flags that returned False.",
    )
    sections_authored: list[str] = Field(
        default_factory=list,
        description="Top-level keys present in the authored material_spec_sheet.",
    )
    material_spec_sheet: dict[str, Any] = Field(
        description="The full structured spec sheet — keep for follow-up turns.",
    )


@tool(
    name="generate_material_spec",
    description=(
        "Author the BRD-grade Material Specification Sheet (BRD 3B) "
        "for a piece — primary structure, secondary materials, hardware, "
        "upholstery, finishing, cost summary. Calls the LLM material-spec "
        "author. Use when the user asks 'what materials should I use', "
        "'spec this in walnut', or for any production-handoff request. "
        "Returns the full sheet plus validation status."
    ),
    timeout_seconds=90.0,
    audit_target_type="material_spec_sheet",
)
async def generate_material_spec(
    ctx: ToolContext,
    input: GenerateMaterialSpecInput,
) -> MaterialSpecOutput:
    req = MaterialSpecRequest(
        theme=input.theme,
        project_name=input.project_name,
        parametric_spec=input.parametric_spec,
        city=input.city,
        sections=list(input.sections) if input.sections else list(_DEFAULT_MATERIAL_SECTIONS),
    )

    try:
        result = await _generate_material_spec_sheet(req)
    except MaterialSpecError as exc:
        # Surface as ToolError → structured error envelope.
        raise ToolError(str(exc)) from exc

    sheet = result.get("material_spec_sheet") or {}
    passed, failed = _summarise_validation(result.get("validation"))

    return MaterialSpecOutput(
        id=str(result.get("id") or "material_spec_sheet"),
        name=str(result.get("name") or "Material Specification Sheet"),
        theme=input.theme,
        city=result.get("city"),
        validation_passed=passed,
        validation_failures=failed,
        sections_authored=sorted(sheet.keys()) if isinstance(sheet, dict) else [],
        material_spec_sheet=sheet,
    )


# ─────────────────────────────────────────────────────────────────────
# 2. generate_manufacturing_spec  — BRD 3C
# ─────────────────────────────────────────────────────────────────────


class GenerateManufacturingSpecInput(BaseModel):
    """LLM input for the manufacturing-spec tool."""

    theme: str = Field(
        description="Theme slug. Required — the spec is theme-grounded.",
        min_length=2,
        max_length=64,
    )
    project_name: str = Field(default="KATHA Project", max_length=200)
    city: str = Field(default="", max_length=80)
    parametric_spec: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "Optional parametric spec. When present, primary species / "
            "finish drive the woodworking + finishing sequences."
        ),
    )
    sections: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_MANUFACTURING_SECTIONS),
        description=(
            "Subset of sections to author. Default is all four: "
            "woodworking_notes, metal_fabrication_notes, "
            "upholstery_assembly_notes, quality_assurance."
        ),
    )


class ManufacturingSpecOutput(BaseModel):
    id: str
    name: str
    theme: str
    city: Optional[str] = None
    validation_passed: bool
    validation_failures: list[str] = Field(default_factory=list)
    sections_authored: list[str] = Field(default_factory=list)
    manufacturing_spec: dict[str, Any]


@tool(
    name="generate_manufacturing_spec",
    description=(
        "Author the BRD-grade Manufacturing Specification (BRD 3C) — "
        "woodworking precision, joinery methods, finishing sequence, "
        "metal fabrication notes, upholstery assembly, QA gates, "
        "lead time, MOQ. Calls the LLM manufacturing-spec author. "
        "Use when the user wants to know 'how this gets built' or "
        "needs to brief a fabricator. Returns the full structured spec."
    ),
    timeout_seconds=90.0,
    audit_target_type="manufacturing_spec",
)
async def generate_manufacturing_spec(
    ctx: ToolContext,
    input: GenerateManufacturingSpecInput,
) -> ManufacturingSpecOutput:
    req = ManufacturingSpecRequest(
        theme=input.theme,
        project_name=input.project_name,
        parametric_spec=input.parametric_spec,
        city=input.city,
        sections=list(input.sections) if input.sections else list(_DEFAULT_MANUFACTURING_SECTIONS),
    )

    try:
        result = await _generate_manufacturing_spec(req)
    except ManufacturingSpecError as exc:
        raise ToolError(str(exc)) from exc

    spec = result.get("manufacturing_spec") or {}
    passed, failed = _summarise_validation(result.get("validation"))

    return ManufacturingSpecOutput(
        id=str(result.get("id") or "manufacturing_spec"),
        name=str(result.get("name") or "Manufacturing Specification"),
        theme=input.theme,
        city=result.get("city"),
        validation_passed=passed,
        validation_failures=failed,
        sections_authored=sorted(spec.keys()) if isinstance(spec, dict) else [],
        manufacturing_spec=spec,
    )


# ─────────────────────────────────────────────────────────────────────
# 3. generate_mep_spec  — BRD 3D
# ─────────────────────────────────────────────────────────────────────


class RoomDimensionsInput(BaseModel):
    """Mirror of :class:`app.services.mep_spec_service.RoomDimensions`."""

    length_m: float = Field(gt=0, le=200, description="Room length in metres.")
    width_m: float = Field(gt=0, le=200, description="Room width in metres.")
    height_m: float = Field(gt=0, le=15, description="Floor-to-ceiling height in metres.")


class GenerateMEPSpecInput(BaseModel):
    """LLM input for the MEP-spec tool."""

    room_use_type: str = Field(
        description=(
            "Room use slug — bedroom | living_room | kitchen | bathroom | "
            "office_general | conference_room | retail | restaurant_dining | "
            "restaurant_kitchen | classroom | hotel_room. Drives ACH, "
            "cooling load factor, power density, and equipment shortlist."
        ),
        min_length=2,
        max_length=64,
    )
    dimensions: RoomDimensionsInput = Field(
        description="Room length / width / height in metres.",
    )
    project_name: str = Field(default="KATHA Project", max_length=200)
    room_name: str = Field(default="Primary space", max_length=120)
    occupancy: int = Field(
        default=0,
        ge=0,
        le=2000,
        description="Design occupancy. 0 = unspecified; the LLM will infer from use type.",
    )
    city: str = Field(default="", max_length=80)
    theme: str = Field(default="", max_length=64)
    fixtures: list[str] = Field(
        default_factory=list,
        description=(
            "Plumbing fixtures (DFU keys: water_closet, urinal, "
            "wash_basin, kitchen_sink, shower, bathtub, floor_drain, "
            "washing_machine). Empty for non-wet rooms."
        ),
    )
    sections: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_MEP_SECTIONS),
        description=(
            "Subset of sections. Default is all four: hvac, electrical, "
            "plumbing, cost."
        ),
    )


class MEPSpecOutput(BaseModel):
    id: str
    name: str
    room_use_type: str
    city: Optional[str] = None
    validation_passed: bool
    validation_failures: list[str] = Field(default_factory=list)
    sections_authored: list[str] = Field(default_factory=list)
    mep_spec: dict[str, Any]


@tool(
    name="generate_mep_spec",
    description=(
        "Author the BRD-grade MEP Specification (BRD 3D) for a single "
        "room — HVAC sizing (ACH, CFM, ductwork, equipment tonnage + "
        "BTU), electrical (lighting circuits, panel, outlet count), "
        "plumbing (fixtures, DFU, drain + vent sizing), and indicative "
        "MEP system cost. Calls the LLM MEP-spec author. Use for "
        'consultant-quality output when the user asks "size the MEP for '
        'this room" or needs handoff-ready documentation.'
    ),
    timeout_seconds=90.0,
    audit_target_type="mep_spec",
)
async def generate_mep_spec(
    ctx: ToolContext,
    input: GenerateMEPSpecInput,
) -> MEPSpecOutput:
    req = MEPSpecRequest(
        project_name=input.project_name,
        room_name=input.room_name,
        room_use_type=input.room_use_type,
        dimensions=RoomDimensions(
            length_m=input.dimensions.length_m,
            width_m=input.dimensions.width_m,
            height_m=input.dimensions.height_m,
        ),
        occupancy=input.occupancy,
        city=input.city,
        theme=input.theme,
        fixtures=list(input.fixtures or []),
        sections=list(input.sections) if input.sections else list(_DEFAULT_MEP_SECTIONS),
    )

    try:
        result = await _generate_mep_spec(req)
    except MEPSpecError as exc:
        raise ToolError(str(exc)) from exc

    spec = result.get("mep_spec") or {}
    passed, failed = _summarise_validation(result.get("validation"))

    return MEPSpecOutput(
        id=str(result.get("id") or "mep_spec"),
        name=str(result.get("name") or "MEP Specification"),
        room_use_type=str(result.get("room_use_type") or input.room_use_type),
        city=result.get("city"),
        validation_passed=passed,
        validation_failures=failed,
        sections_authored=sorted(spec.keys()) if isinstance(spec, dict) else [],
        mep_spec=spec,
    )
