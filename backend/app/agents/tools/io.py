"""Stage 4H — import / export tools.

Eight tools that wrap the BRD Layer 5A (export) + 5B (import) services
so the agent can move designs in and out of the platform during a chat.

Discovery / read tools (no audit):

- :func:`list_export_formats` — what can I export? Returns the 15
  registered formats grouped by family (document / cad_2d / cad_3d /
  3d_mesh / bim / cnc / data / interactive) with capabilities.
- :func:`list_import_formats` — what can I import? Returns the
  supported file-extension list from the deterministic parsers.
- :func:`list_export_recipients` — who can I export to? Returns the
  10 canonical recipient roles with their preferred format families.

Project-scoped read:

- :func:`build_spec_bundle_for_current` — assemble the spec bundle
  (meta + material + manufacturing + mep + cost) from the current
  project's latest design-graph version. The exporters consume this.

Project-scoped write (audit):

- :func:`export_design_bundle` — run a registered exporter against
  the current project's latest bundle. Returns content_type +
  filename + size + base64-encoded bytes (capped at 32 KB to keep
  LLM context manageable; larger files surface a flag).

Stateless deterministic:

- :func:`parse_import_file` — run the deterministic importer on
  base64-encoded bytes. No LLM, no DB write.

LLM-heavy:

- :func:`generate_import_manifest` — author the ingestion manifest
  for a list of pre-parsed import payloads.
- :func:`generate_export_manifest` — author the per-recipient
  export recommendation manifest.

Project-scope guard
-------------------
``build_spec_bundle_for_current`` and ``export_design_bundle`` read
``ctx.project_id`` and refuse to run without it — they need a
specific project's latest version.

Cost guardrails
---------------
- Read / parse tools: 30 s timeout.
- Export bundle (deterministic per-format): 60 s.
- LLM advisors: 90 s (matches Stage 4D specs).
"""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.services.design_graph_service import get_latest_version
from app.services.export_advisor_service import (
    FORMAT_CATALOGUE,
    RECIPIENT_FAMILIES,
    ExportAdvisorError,
    ExportAdvisorRequest,
    generate_export_manifest as _generate_export_manifest,
)
from app.services.exporters import (
    available_formats as _available_formats,
    export as _export,
)
from app.services.import_advisor_service import (
    ImportAdvisorError,
    ImportAdvisorRequest,
    ImportPayload,
    generate_import_manifest as _generate_import_manifest,
)
from app.services.importers import (
    parse as _parse_file,
    supported_extensions as _supported_extensions,
)
from app.services.specs import build_spec_bundle as _build_spec_bundle

logger = logging.getLogger(__name__)


# Threshold above which we omit raw content from the LLM-visible output
# to keep the agent's context window sane. The bytes are still produced
# by the exporter — just not echoed back into the chat surface.
_INLINE_BYTES_LIMIT = 32 * 1024  # 32 KB


# ─────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────


def _require_project(ctx: ToolContext) -> str:
    """Pull project_id off the context or raise ToolError."""
    project_id = ctx.project_id
    if not project_id:
        raise ToolError(
            "No project_id on the agent context. The export / spec "
            "bundle tools require a project scope — open a project "
            "first or pass project_id when starting the chat session."
        )
    return project_id


async def _load_latest_graph(ctx: ToolContext, project_id: str) -> dict[str, Any]:
    """Load the latest design-graph version's data, or raise ToolError."""
    latest = await get_latest_version(ctx.session, project_id)
    if latest is None:
        raise ToolError(
            f"No design-graph versions found for project {project_id}. "
            "Run generate_initial_design first."
        )
    return getattr(latest, "graph_data", {}) or {}


# ─────────────────────────────────────────────────────────────────────
# 1. list_export_formats
# ─────────────────────────────────────────────────────────────────────


class ListExportFormatsInput(BaseModel):
    """No fields — purely a discovery call."""

    pass


class ExportFormatEntry(BaseModel):
    key: str
    family: str
    label: str
    extension: str
    best_for: list[str] = Field(default_factory=list)
    compatible_with: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    precision: Optional[str] = None


class ListExportFormatsOutput(BaseModel):
    formats: list[ExportFormatEntry]
    families: dict[str, list[str]] = Field(
        description="Map of family slug → list of format keys in that family.",
    )
    count: int


@tool(
    name="list_export_formats",
    description=(
        "List every registered export format with its family, label, "
        "extension, best-for use cases, compatible software, and "
        "preconditions on the spec bundle. Use to answer 'what formats "
        "can I export to' or to pick a format for a specific recipient. "
        "No project scope required."
    ),
    timeout_seconds=30.0,
)
async def list_export_formats(
    ctx: ToolContext,
    input: ListExportFormatsInput,
) -> ListExportFormatsOutput:
    registered = set(_available_formats())
    entries: list[ExportFormatEntry] = []
    families: dict[str, list[str]] = {}
    for key, meta in FORMAT_CATALOGUE.items():
        if key not in registered:
            # Catalogue lists a format the registry doesn't expose —
            # skip rather than emit a phantom entry.
            continue
        entry = ExportFormatEntry(
            key=key,
            family=str(meta.get("family") or ""),
            label=str(meta.get("label") or key),
            extension=str(meta.get("extension") or f".{key}"),
            best_for=list(meta.get("best_for") or []),
            compatible_with=list(meta.get("compatible_with") or []),
            preconditions=list(meta.get("preconditions") or []),
            precision=meta.get("precision") if isinstance(meta.get("precision"), str) else None,
        )
        entries.append(entry)
        families.setdefault(entry.family, []).append(key)
    return ListExportFormatsOutput(
        formats=entries,
        families={k: sorted(v) for k, v in families.items()},
        count=len(entries),
    )


# ─────────────────────────────────────────────────────────────────────
# 2. list_import_formats
# ─────────────────────────────────────────────────────────────────────


class ListImportFormatsInput(BaseModel):
    pass


class ListImportFormatsOutput(BaseModel):
    extensions: list[str]
    count: int


@tool(
    name="list_import_formats",
    description=(
        "List every file extension the deterministic importers can "
        "parse — pdf, png/jpg, dxf/dwg, step/stp/iges, obj/fbx/gltf, "
        "csv, xlsx/xls, docx, txt/md. Use before asking the user to "
        "upload, or to advise on file conversion. No project scope "
        "required."
    ),
    timeout_seconds=30.0,
)
async def list_import_formats(
    ctx: ToolContext,
    input: ListImportFormatsInput,
) -> ListImportFormatsOutput:
    exts = _supported_extensions()
    return ListImportFormatsOutput(extensions=list(exts), count=len(exts))


# ─────────────────────────────────────────────────────────────────────
# 3. list_export_recipients
# ─────────────────────────────────────────────────────────────────────


class ListExportRecipientsInput(BaseModel):
    pass


class ExportRecipientEntry(BaseModel):
    role: str
    preferred_families: list[str] = Field(
        description=(
            "Format families this recipient typically wants — document, "
            "cad_2d, cad_3d, 3d_mesh, bim, cnc, data, interactive."
        ),
    )


class ListExportRecipientsOutput(BaseModel):
    recipients: list[ExportRecipientEntry]
    count: int


@tool(
    name="list_export_recipients",
    description=(
        "List the canonical recipient roles for export-manifest "
        "generation — client, architect, interior_designer, fabricator, "
        "cnc_shop, rendering_studio, bim_consultant, project_manager, "
        "structural_engineer, mep_consultant — each annotated with the "
        "format families they typically want. Use to scope a "
        "generate_export_manifest call. No project scope required."
    ),
    timeout_seconds=30.0,
)
async def list_export_recipients(
    ctx: ToolContext,
    input: ListExportRecipientsInput,
) -> ListExportRecipientsOutput:
    rows = [
        ExportRecipientEntry(role=role, preferred_families=list(families))
        for role, families in RECIPIENT_FAMILIES.items()
    ]
    return ListExportRecipientsOutput(recipients=rows, count=len(rows))


# ─────────────────────────────────────────────────────────────────────
# 4. build_spec_bundle_for_current
# ─────────────────────────────────────────────────────────────────────


class BuildSpecBundleInput(BaseModel):
    project_name: str = Field(
        default="KATHA Project",
        max_length=200,
        description="Display name to embed in the bundle's meta block.",
    )


class SpecBundleOutput(BaseModel):
    project_id: str
    version: int
    objects_count: int
    meta: dict[str, Any] = Field(default_factory=dict)
    bundle_status: dict[str, bool] = Field(
        description=(
            "Readiness flag per bundle section — keys: meta, material, "
            "manufacturing, mep, cost. The export advisor uses this to "
            "decide which formats are exportable."
        ),
    )
    bundle: dict[str, Any] = Field(
        description="Full spec bundle the exporters consume.",
    )


@tool(
    name="build_spec_bundle_for_current",
    description=(
        "Assemble the structured spec bundle (meta + material + "
        "manufacturing + mep + cost) from the current project's latest "
        "design-graph version. This is the payload every exporter "
        "consumes. Use as a precursor to export_design_bundle, or to "
        "preview what data is ready for export. Requires a project + "
        "at least one prior version."
    ),
    timeout_seconds=30.0,
)
async def build_spec_bundle_for_current(
    ctx: ToolContext,
    input: BuildSpecBundleInput,
) -> SpecBundleOutput:
    project_id = _require_project(ctx)
    latest = await get_latest_version(ctx.session, project_id)
    if latest is None:
        raise ToolError(
            f"No design-graph versions found for project {project_id}. "
            "Run generate_initial_design first."
        )
    graph = getattr(latest, "graph_data", {}) or {}
    bundle = _build_spec_bundle(graph, project_name=input.project_name)

    # Readiness flags — non-empty section dict counts as ready.
    bundle_status = {
        key: bool(bundle.get(key))
        for key in ("meta", "material", "manufacturing", "mep", "cost")
    }

    return SpecBundleOutput(
        project_id=project_id,
        version=int(getattr(latest, "version", 0)),
        objects_count=int(bundle.get("objects_count") or 0),
        meta=dict(bundle.get("meta") or {}),
        bundle_status=bundle_status,
        bundle=bundle,
    )


# ─────────────────────────────────────────────────────────────────────
# 5. export_design_bundle
# ─────────────────────────────────────────────────────────────────────


class ExportDesignBundleInput(BaseModel):
    format_key: str = Field(
        description=(
            "Which exporter to run — one of pdf | docx | xlsx | pptx | "
            "html | dxf | obj | gltf | fbx | ifc | step | iges | gcode "
            "| cam_prep | geojson. Call list_export_formats first if "
            "you're unsure what's available."
        ),
        min_length=1,
        max_length=32,
    )
    project_name: str = Field(default="KATHA Project", max_length=200)


class ExportDesignBundleOutput(BaseModel):
    project_id: str
    version: int
    format_key: str
    content_type: str
    filename: str
    size_bytes: int
    content_base64: Optional[str] = Field(
        default=None,
        description=(
            "Base64-encoded file content. Omitted when the file is "
            "larger than the inline limit; the export still ran "
            "successfully and the agent UI can fetch the bytes via a "
            "side-channel keyed on project_id + filename."
        ),
    )
    inline_bytes_omitted: bool = Field(
        default=False,
        description="True when content_base64 was omitted because the file exceeds the inline limit.",
    )
    inline_bytes_limit: int = Field(default=_INLINE_BYTES_LIMIT)


@tool(
    name="export_design_bundle",
    description=(
        "Run a registered exporter (pdf / docx / xlsx / dxf / obj / "
        "gltf / fbx / ifc / step / iges / gcode / cam_prep / geojson "
        "/ pptx / html) against the current project's latest design "
        "bundle. Returns content_type + filename + size_bytes + "
        "(if small enough) base64 content. Use after the user picks "
        "a format. Requires a project + at least one prior version."
    ),
    timeout_seconds=60.0,
    audit_target_type="export_bundle",
)
async def export_design_bundle(
    ctx: ToolContext,
    input: ExportDesignBundleInput,
) -> ExportDesignBundleOutput:
    project_id = _require_project(ctx)
    graph = await _load_latest_graph(ctx, project_id)
    bundle = _build_spec_bundle(graph, project_name=input.project_name)

    # Re-resolve the version for the output (cheap; we just used it).
    latest = await get_latest_version(ctx.session, project_id)
    version = int(getattr(latest, "version", 0)) if latest else 0

    try:
        result = _export(input.format_key, bundle, graph)
    except ValueError as exc:
        # Unsupported format — translate to a structured envelope.
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        # Exporter implementation failed (missing optional dep, etc.).
        raise ToolError(f"Export failed: {exc}") from exc

    payload = result.get("bytes") or b""
    size = len(payload)
    omit_bytes = size > _INLINE_BYTES_LIMIT
    encoded = None if omit_bytes else base64.b64encode(payload).decode("ascii")

    return ExportDesignBundleOutput(
        project_id=project_id,
        version=version,
        format_key=input.format_key.lower(),
        content_type=str(result.get("content_type") or "application/octet-stream"),
        filename=str(result.get("filename") or f"export.{input.format_key.lower()}"),
        size_bytes=size,
        content_base64=encoded,
        inline_bytes_omitted=omit_bytes,
    )


# ─────────────────────────────────────────────────────────────────────
# 6. parse_import_file
# ─────────────────────────────────────────────────────────────────────


class ParseImportFileInput(BaseModel):
    filename: str = Field(
        description=(
            "Original filename including extension — drives importer "
            "selection. Examples: 'site_plan.dxf', 'brief.pdf', "
            "'materials.xlsx'."
        ),
        min_length=1,
        max_length=255,
    )
    content_base64: str = Field(
        description=(
            "Base64-encoded file contents. The agent typically gets "
            "this from a prior chat upload — pass it through verbatim."
        ),
        min_length=1,
    )


class ParseImportFileOutput(BaseModel):
    format: str
    filename: str
    size_bytes: int
    summary: str
    extracted: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


@tool(
    name="parse_import_file",
    description=(
        "Run the deterministic importer on a base64-encoded uploaded "
        "file. Returns the structured payload — extracted text, "
        "dimensions, geometry, or tabular rows depending on the "
        "format. Pass the result of this tool into "
        "generate_import_manifest to get an ingestion plan. Stateless — "
        "no LLM, no DB write."
    ),
    timeout_seconds=60.0,
)
async def parse_import_file(
    ctx: ToolContext,
    input: ParseImportFileInput,
) -> ParseImportFileOutput:
    try:
        payload = base64.b64decode(input.content_base64, validate=False)
    except (ValueError, TypeError) as exc:
        raise ToolError(f"content_base64 is not valid base64: {exc}") from exc

    try:
        parsed = _parse_file(input.filename, payload)
    except Exception as exc:  # noqa: BLE001
        # The route layer already handles this defensively; mirror it.
        raise ToolError(f"Importer crashed for {input.filename!r}: {exc}") from exc

    return ParseImportFileOutput(
        format=str(parsed.get("format") or "unknown"),
        filename=str(parsed.get("filename") or input.filename),
        size_bytes=int(parsed.get("size_bytes") or len(payload)),
        summary=str(parsed.get("summary") or ""),
        extracted=dict(parsed.get("extracted") or {}),
        warnings=list(parsed.get("warnings") or []),
    )


# ─────────────────────────────────────────────────────────────────────
# 7. generate_import_manifest
# ─────────────────────────────────────────────────────────────────────


class ImportPayloadInput(BaseModel):
    """One pre-parsed file (typically the result of parse_import_file)."""

    format: str = Field(max_length=64)
    filename: str = Field(max_length=255)
    size_bytes: int = Field(default=0, ge=0)
    summary: str = Field(default="", max_length=2000)
    extracted: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class GenerateImportManifestInput(BaseModel):
    imports: list[ImportPayloadInput] = Field(
        description=(
            "List of pre-parsed import payloads — call parse_import_file "
            "once per uploaded file and pass the results through here. "
            "At least one is required."
        ),
        min_length=1,
        max_length=20,
    )
    project_name: str = Field(default="KATHA Project", max_length=200)
    theme: str = Field(default="", max_length=64)
    existing_brief: dict[str, Any] = Field(default_factory=dict)
    existing_graph: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=600)


class ImportManifestOutput(BaseModel):
    id: str = Field(default="import_manifest")
    name: str = Field(default="Import Manifest")
    import_count: int
    validation_passed: bool
    validation_failures: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(
        description="Full LLM-authored ingestion manifest.",
    )


def _summarise_validation(validation: Optional[dict[str, Any]]) -> tuple[bool, list[str]]:
    if not validation:
        return True, []
    failed: list[str] = []
    for key, value in validation.items():
        if isinstance(value, bool) and value is False:
            failed.append(key)
    return (len(failed) == 0), failed


@tool(
    name="generate_import_manifest",
    description=(
        "Author the LLM ingestion manifest for a list of pre-parsed "
        "uploads — extractions per file, conflicts vs the existing "
        "brief / graph, and a merge plan. Use after running "
        "parse_import_file on each upload. LLM-heavy. Up to 20 imports "
        "per call."
    ),
    timeout_seconds=90.0,
    audit_target_type="import_manifest",
)
async def generate_import_manifest(
    ctx: ToolContext,
    input: GenerateImportManifestInput,
) -> ImportManifestOutput:
    payloads = [
        ImportPayload(
            format=p.format,
            filename=p.filename,
            size_bytes=p.size_bytes,
            summary=p.summary,
            extracted=p.extracted,
            warnings=p.warnings,
        )
        for p in input.imports
    ]
    req = ImportAdvisorRequest(
        project_name=input.project_name,
        theme=input.theme,
        existing_brief=input.existing_brief,
        existing_graph=input.existing_graph,
        imports=payloads,
        notes=input.notes,
    )
    try:
        result = await _generate_import_manifest(req)
    except ImportAdvisorError as exc:
        raise ToolError(str(exc)) from exc

    # The service returns the manifest under various keys depending on
    # the run; fall back gracefully.
    manifest = (
        result.get("import_manifest")
        or result.get("manifest")
        or {k: v for k, v in result.items() if k not in {"knowledge", "validation"}}
    )
    passed, failed = _summarise_validation(result.get("validation"))

    return ImportManifestOutput(
        id=str(result.get("id") or "import_manifest"),
        name=str(result.get("name") or "Import Manifest"),
        import_count=len(input.imports),
        validation_passed=passed,
        validation_failures=failed,
        manifest=manifest if isinstance(manifest, dict) else {},
    )


# ─────────────────────────────────────────────────────────────────────
# 8. generate_export_manifest
# ─────────────────────────────────────────────────────────────────────


class GenerateExportManifestInput(BaseModel):
    recipients: list[str] = Field(
        description=(
            "Recipient roles for the export pack — pick from "
            "list_export_recipients. Defaults to client + fabricator + "
            "architect when omitted."
        ),
        default_factory=lambda: ["client", "fabricator", "architect"],
        max_length=10,
    )
    bundle_status: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Bundle readiness flags — keys: meta, material, "
            "manufacturing, mep, cost. Pull from "
            "build_spec_bundle_for_current.bundle_status. Missing "
            "keys default to False."
        ),
    )
    downstream_software: list[str] = Field(
        default_factory=list,
        max_length=20,
        description=(
            "Optional list of downstream tools the recipient uses — "
            "Revit, Rhino, AutoCAD, Fusion 360, etc. Drives the "
            "advisor's format-fit recommendations."
        ),
    )
    project_name: str = Field(default="KATHA Project", max_length=200)
    piece_name: str = Field(default="Primary piece", max_length=160)
    theme: str = Field(default="", max_length=64)
    notes: str = Field(default="", max_length=600)


class ExportManifestOutput(BaseModel):
    id: str = Field(default="export_manifest")
    name: str = Field(default="Export Manifest")
    recipient_count: int
    validation_passed: bool
    validation_failures: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(
        description="Full LLM-authored export manifest.",
    )


@tool(
    name="generate_export_manifest",
    description=(
        "Author the LLM export manifest — per-format capabilities, "
        "per-recipient recommendations, and a primary handoff format. "
        "Use after build_spec_bundle_for_current to advise the user "
        "which formats to send to which recipient given the current "
        "bundle's readiness. LLM-heavy."
    ),
    timeout_seconds=90.0,
    audit_target_type="export_manifest",
)
async def generate_export_manifest(
    ctx: ToolContext,
    input: GenerateExportManifestInput,
) -> ExportManifestOutput:
    req = ExportAdvisorRequest(
        project_name=input.project_name,
        piece_name=input.piece_name,
        theme=input.theme,
        recipients=list(input.recipients),
        downstream_software=list(input.downstream_software),
        bundle_status=dict(input.bundle_status),
        notes=input.notes,
    )
    try:
        result = await _generate_export_manifest(req)
    except ExportAdvisorError as exc:
        raise ToolError(str(exc)) from exc

    manifest = (
        result.get("export_manifest")
        or result.get("manifest")
        or {k: v for k, v in result.items() if k not in {"knowledge", "validation"}}
    )
    passed, failed = _summarise_validation(result.get("validation"))

    return ExportManifestOutput(
        id=str(result.get("id") or "export_manifest"),
        name=str(result.get("name") or "Export Manifest"),
        recipient_count=len(input.recipients),
        validation_passed=passed,
        validation_failures=failed,
        manifest=manifest if isinstance(manifest, dict) else {},
    )
