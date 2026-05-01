"""Stage 9 agent tool — haptic export.

One tool, per BRD §Layer 7 / Stage 9 plan:

- :func:`export_haptic_payload` — given a saved design-graph version
  for the current project, produce the full haptic export payload
  the hardware driver will consume. Read-only against the design
  graph; writes nothing back.

The audit target is ``haptic_export`` even though the tool doesn't
mutate domain data — this lets ops trace which exports were
generated for which projects, which catalog version was active,
and how many materials fell back to the generic profile.

Owner / project scope
---------------------
The tool refuses to operate on a graph that doesn't belong to the
current project (``ctx.project_id``). Cross-owner reads return a
clean :class:`ToolError` instead of leaking existence — same
pattern as the Stage 8 client tools.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents.tool import ToolContext, ToolError, tool
from app.haptic.exporter import build_haptic_payload
from app.models.orm import DesignGraphVersion

logger = logging.getLogger(__name__)


def _require_project(ctx: ToolContext) -> str:
    if not ctx.project_id:
        raise ToolError(
            "No project_id on the agent context. Haptic export "
            "requires a project scope."
        )
    return ctx.project_id


# ─────────────────────────────────────────────────────────────────────
# 1. export_haptic_payload
# ─────────────────────────────────────────────────────────────────────


class ExportHapticPayloadInput(BaseModel):
    graph_version_id: Optional[str] = Field(
        default=None,
        description=(
            "ID of the saved DesignGraphVersion to export. Omit to "
            "auto-pick the latest version of the current project."
        ),
        max_length=64,
    )
    version: Optional[int] = Field(
        default=None,
        ge=0,
        description=(
            "Alternative to graph_version_id — pick the version of "
            "the current project by its sequential number (1, 2, ...)."
        ),
    )


class HapticExportEnvelope(BaseModel):
    """Provenance / version stamping of the payload."""

    schema_version: str
    catalog_version: str
    graph_version_id: str
    project_id: str
    design_version: int
    generated_at: str


class HapticExportValidation(BaseModel):
    """Resolution outcome for materials + object types."""

    all_materials_mapped: bool
    requested_materials: list[str] = Field(default_factory=list)
    mapped_materials: list[str] = Field(default_factory=list)
    fallback_materials: list[str] = Field(default_factory=list)
    missing_object_types: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExportHapticPayloadOutput(BaseModel):
    """Wraps the BRD §Layer 7 payload + a quick summary block.

    The ``payload`` dict is the artefact hardware vendors consume
    end-to-end. The ``summary`` is a flat read for the agent's
    reasoning step ("export covered 6 materials, 1 fell back to
    generic, schema 9.0.0, catalog 2026.05.01").
    """

    envelope: HapticExportEnvelope
    validation: HapticExportValidation
    summary: dict[str, Any]
    payload: dict[str, Any]


# ─────────────────────────────────────────────────────────────────────
# Helpers — graph version resolution with project-scope guard.
# ─────────────────────────────────────────────────────────────────────


async def _resolve_graph_version(
    ctx: ToolContext,
    *,
    graph_version_id: Optional[str],
    version: Optional[int],
) -> DesignGraphVersion:
    """Find the requested version *and* enforce project scope.

    Cross-project access returns a clean :class:`ToolError` —
    same shape whether the row doesn't exist or it exists under
    another project, so we don't leak existence.
    """
    project_id = _require_project(ctx)

    if graph_version_id:
        stmt = select(DesignGraphVersion).where(
            DesignGraphVersion.id == graph_version_id,
            DesignGraphVersion.project_id == project_id,
        )
    elif version is not None:
        stmt = select(DesignGraphVersion).where(
            DesignGraphVersion.project_id == project_id,
            DesignGraphVersion.version == int(version),
        )
    else:
        # Latest version for the current project.
        stmt = (
            select(DesignGraphVersion)
            .where(DesignGraphVersion.project_id == project_id)
            .order_by(DesignGraphVersion.version.desc())
            .limit(1)
        )

    result = await ctx.session.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise ToolError(
            "No design-graph version found for the current project "
            "matching the requested id/version. Generate or save a "
            "version first."
        )
    return row


@tool(
    name="export_haptic_payload",
    description=(
        "Export the full haptic data structure for a saved design "
        "graph in the current project. Returns a JSON payload "
        "matching BRD §Layer 7 — dimensions in mm, material haptic "
        "properties (texture / temperature / friction / firmness), "
        "interaction parameters (adjustable axes + ranges), and "
        "feedback-loop rules. Hardware drivers consume this directly. "
        "Materials with no catalog profile fall back to the 'generic' "
        "profile and are flagged in the validation block. "
        "Specify graph_version_id or version, or omit both for the "
        "latest version of the project."
    ),
    timeout_seconds=30.0,
    audit_target_type="haptic_export",
)
async def export_haptic_payload(
    ctx: ToolContext,
    input: ExportHapticPayloadInput,
) -> ExportHapticPayloadOutput:
    graph_version = await _resolve_graph_version(
        ctx,
        graph_version_id=input.graph_version_id,
        version=input.version,
    )

    export = await build_haptic_payload(
        ctx.session, graph_version=graph_version,
    )
    payload = export.payload

    envelope = HapticExportEnvelope(
        schema_version=str(payload["schema_version"]),
        catalog_version=str(payload["catalog_version"]),
        graph_version_id=str(payload["graph_version_id"]),
        project_id=str(payload["project_id"]),
        design_version=int(payload["design_version"]),
        generated_at=str(payload["generated_at"]),
    )
    validation_dict = dict(payload.get("validation") or {})
    validation = HapticExportValidation(
        all_materials_mapped=bool(
            validation_dict.get("all_materials_mapped", True)
        ),
        requested_materials=list(
            validation_dict.get("requested_materials") or []
        ),
        mapped_materials=list(
            validation_dict.get("mapped_materials") or []
        ),
        fallback_materials=list(
            validation_dict.get("fallback_materials") or []
        ),
        missing_object_types=list(
            validation_dict.get("missing_object_types") or []
        ),
        warnings=list(validation_dict.get("warnings") or []),
    )

    summary = {
        "schema_version": envelope.schema_version,
        "catalog_version": envelope.catalog_version,
        "design_version": envelope.design_version,
        "room_count": len(payload.get("dimensions", {}).get("rooms", []) or []),
        "object_count": len(
            payload.get("dimensions", {}).get("objects", []) or []
        ),
        "material_count": len(payload.get("materials", []) or []),
        "interaction_count": len(payload.get("interactions", []) or []),
        "feedback_loop_count": len(payload.get("feedback_loops", []) or []),
        "fallback_count": len(validation.fallback_materials),
        "all_materials_mapped": validation.all_materials_mapped,
    }

    return ExportHapticPayloadOutput(
        envelope=envelope,
        validation=validation,
        summary=summary,
        payload=payload,
    )
