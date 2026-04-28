"""LLM-driven Import Advisor (BRD Layer 5B).

Authors an *ingestion manifest* — the document that takes a set of
already-parsed input files and tells the project pipeline how to fold
them into the existing design graph and design brief.

Pipeline contract — same as every other LLM service:

    INPUT (list of parsed payloads from
           app.services.importers.parse + project context)
      → INJECT  (per-file extracts, the design-graph / brief schema
                 the ingestion targets, vocabularies for room types
                 / styles / materials / fixtures)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (every recommended target field is in the schema;
                   every claimed source maps to a parsed payload;
                   merge_strategy is one of the controlled values)
      → OUTPUT  (import_manifest JSON conforming to the BRD template)

The deterministic importers in `app.services.importers` extract raw
data (text, dimensions, geometry, tabular rows). This service writes
the merge plan: which import lands where, what conflicts there are,
and what the studio should review before ingestion.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.knowledge import mep, themes
from app.services.importers import supported_extensions

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
INPUT_KINDS_IN_SCOPE = (
    "design_brief",          # text / docx free-form brief
    "client_specifications", # csv / xlsx of requirements
    "material_pricing",      # csv / xlsx of materials and rates
    "supplier_data",         # csv / xlsx of suppliers
    "budget_parameters",     # csv / xlsx of budget caps
    "site_plan",             # dxf or pdf floor plan
    "reference_design",      # pdf, dxf, step, obj — existing design to mimic
    "reference_image",       # png / jpg — style reference
    "geometry_3d",           # obj / fbx / gltf / step — 3D reference
    "design_drawing",        # pdf with technical drawings
)

TARGET_FIELDS_IN_SCOPE = (
    "brief.title",
    "brief.client_name",
    "brief.budget_inr",
    "brief.timeline_weeks",
    "brief.room_type",
    "brief.style_preference",
    "brief.material_preferences",
    "brief.constraints",
    "graph.room.type",
    "graph.room.dimensions.length",
    "graph.room.dimensions.width",
    "graph.room.dimensions.height",
    "graph.style.primary",
    "graph.materials",
    "graph.objects",
    "graph.site_context",
    "knowledge.material_overrides",
    "knowledge.supplier_overrides",
)

MERGE_STRATEGIES_IN_SCOPE = (
    "overwrite",      # replace existing field with imported value
    "append",         # add to existing list/array
    "merge",          # deep-merge maps
    "fill_if_empty",  # set only when target is missing
    "review",         # human approval needed before applying
    "ignore",         # informational only
)


# ── Request schema ──────────────────────────────────────────────────────────


class ImportPayload(BaseModel):
    """One pre-parsed file (from app.services.importers.parse)."""
    format: str
    filename: str
    size_bytes: int = 0
    summary: str = ""
    extracted: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ImportAdvisorRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    theme: str = Field(default="", max_length=64)
    existing_brief: dict[str, Any] = Field(default_factory=dict)
    existing_graph: dict[str, Any] = Field(default_factory=dict)
    imports: list[ImportPayload] = Field(default_factory=list)
    notes: str = Field(default="", max_length=600)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def build_import_advisor_knowledge(req: ImportAdvisorRequest) -> dict[str, Any]:
    pack = themes.get(req.theme) if req.theme else None
    return {
        "project": {
            "name": req.project_name,
            "theme": req.theme or None,
            "notes": req.notes or None,
            "existing_brief_keys": sorted(list(req.existing_brief.keys())),
            "existing_graph_keys": sorted(list(req.existing_graph.keys())),
        },
        "imports": [p.model_dump() for p in (req.imports or [])],
        "schema": {
            "target_fields_in_scope": list(TARGET_FIELDS_IN_SCOPE),
            "merge_strategies_in_scope": list(MERGE_STRATEGIES_IN_SCOPE),
            "input_kinds_in_scope": list(INPUT_KINDS_IN_SCOPE),
            "supported_extensions": supported_extensions(),
        },
        "vocab": {
            "room_use_types_in_scope": list(mep.AIR_CHANGES_PER_HOUR.keys()),
            "theme_known": (pack or {}).get("display_name"),
            "themes_known": themes.list_names(),
        },
        "existing": {
            "brief": req.existing_brief or {},
            "graph_summary": {
                "room": (req.existing_graph or {}).get("room"),
                "style": (req.existing_graph or {}).get("style"),
                "material_count": len((req.existing_graph or {}).get("materials") or []),
                "object_count": len((req.existing_graph or {}).get("objects") or []),
            },
        },
    }


# ── System prompt ───────────────────────────────────────────────────────────


IMPORT_ADVISOR_SYSTEM_PROMPT = """You are a senior project lead authoring the *Import Manifest* (BRD Layer 5B) — the document that takes a set of already-parsed input files and tells the studio how to fold them into the existing design brief and design graph.

Read the [KNOWLEDGE] block — imports (each carrying its parsed extract), target_fields_in_scope (the design graph + brief fields ingestion is allowed to touch), merge_strategies_in_scope, input_kinds_in_scope, room_use_types_in_scope, and existing project state — and produce a structured import_manifest JSON.

Studio voice — short, decisive, no marketing prose. The deterministic importers already extracted text / dimensions / geometry / rows. Your job is to LABEL each import, MAP its findings onto target fields, FLAG conflicts with the existing project, and CHOOSE a merge strategy.

Hard rules for header:
- Each entry in input_summary MUST mirror an entry in knowledge.imports — same filename, format, size_bytes, summary verbatim.
- input_kind MUST be in input_kinds_in_scope.

Hard rules for extractions[]:
- One entry per import file.
- source.filename MUST match an imports[].filename verbatim.
- detected_fields[] is a list of the brief / graph fields this file plausibly fills. Each entry's target MUST be in target_fields_in_scope.
- Every detected_field carries a value, source_path (where in extracted{} it was lifted from, e.g. "extracted.brief_signals.budgets[0].value"), and a confidence in {high, medium, low}. Cite low for inferred values; high only when the file states the value explicitly.

Hard rules for conflicts[]:
- Emit one entry per detected_field whose target already has a value in existing.brief / existing.graph.
- Carry both existing_value and incoming_value. Cite the merge strategy you recommend.

Hard rules for merge_plan[]:
- One entry per (target, merge_strategy) decision. strategy MUST be in merge_strategies_in_scope.
- 'review' is mandatory for any conflict where existing_value is non-empty AND incoming confidence is medium or low.
- 'overwrite' requires high confidence AND no existing value (or human note in rationale).
- 'fill_if_empty' is the safe default for new brief / graph fields with no existing value.
- 'append' is correct for graph.materials and graph.objects when the incoming file adds new entries.
- 'ignore' is correct for reference-only files (style image, render reference) that should not flow into the graph but should be remembered as inspiration.

Hard rules for warnings[]:
- Surface every importer warning verbatim from imports[].warnings.
- Add a warning when a file's input_kind is 'site_plan' but no dimensions were extracted.
- Add a warning when geometry_3d / reference_design extents fall outside [0.5, 60] m on any axis (suspicious unit scale).

Hard rules for next_steps[]:
- Three to six bullets ordered by priority. Each bullet names a concrete action ("Confirm budget ₹12 L from the brief", "Verify site-plan units — DXF reports 12000 mm walls").

Never invent target fields, merge strategies, or input kinds. Snap every value to the catalogue."""


# ── JSON schema ─────────────────────────────────────────────────────────────


def _input_summary_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "filename": {"type": "string"},
            "format": {"type": "string"},
            "size_bytes": {"type": "integer"},
            "summary": {"type": "string"},
            "input_kind": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": [
            "filename", "format", "size_bytes",
            "summary", "input_kind", "rationale",
        ],
        "additionalProperties": False,
    }


def _detected_field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "target": {"type": "string"},                # TARGET_FIELDS_IN_SCOPE
            "value": {"type": "string"},                 # always stringified
            "source_path": {"type": "string"},           # JSON path into extracted{}
            "confidence": {"type": "string"},            # high / medium / low
            "rationale": {"type": "string"},
        },
        "required": [
            "target", "value", "source_path",
            "confidence", "rationale",
        ],
        "additionalProperties": False,
    }


def _extraction_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "source_filename": {"type": "string"},
            "detected_fields": {
                "type": "array",
                "items": _detected_field_schema(),
            },
        },
        "required": ["source_filename", "detected_fields"],
        "additionalProperties": False,
    }


def _conflict_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "existing_value": {"type": "string"},
            "incoming_value": {"type": "string"},
            "incoming_source": {"type": "string"},        # filename
            "recommended_strategy": {"type": "string"},   # merge strategy
            "rationale": {"type": "string"},
        },
        "required": [
            "target", "existing_value", "incoming_value",
            "incoming_source", "recommended_strategy", "rationale",
        ],
        "additionalProperties": False,
    }


def _merge_plan_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "target": {"type": "string"},
            "strategy": {"type": "string"},
            "incoming_value": {"type": "string"},
            "incoming_source": {"type": "string"},
            "rationale": {"type": "string"},
        },
        "required": [
            "target", "strategy", "incoming_value",
            "incoming_source", "rationale",
        ],
        "additionalProperties": False,
    }


IMPORT_ADVISOR_SCHEMA: dict[str, Any] = {
    "name": "import_manifest",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "header": {
                "type": "object",
                "properties": {
                    "project": {"type": "string"},
                    "theme": {"type": "string"},
                    "date_iso": {"type": "string"},
                    "import_count": {"type": "integer"},
                },
                "required": ["project", "theme", "date_iso", "import_count"],
                "additionalProperties": False,
            },
            "input_summary": {
                "type": "array",
                "items": _input_summary_schema(),
            },
            "extractions": {
                "type": "array",
                "items": _extraction_schema(),
            },
            "conflicts": {
                "type": "array",
                "items": _conflict_schema(),
            },
            "merge_plan": {
                "type": "array",
                "items": _merge_plan_schema(),
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "next_steps": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header", "input_summary", "extractions",
            "conflicts", "merge_plan", "warnings",
            "next_steps", "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: ImportAdvisorRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Theme: {req.theme or '(not specified)'}\n"
        f"- Imports: {len(req.imports)}\n"
        f"- Existing brief keys: {len(req.existing_brief)}\n"
        f"- Existing graph keys: {len(req.existing_graph)}\n"
        f"- Date (UTC ISO): {today}\n"
        f"- Notes: {req.notes or '(none)'}\n\n"
        "Produce the import_manifest JSON. Label every file with an "
        "input_kind, extract detected fields onto target_fields_in_scope, "
        "list every conflict with the existing project, propose a merge "
        "plan with explicit strategies, and surface warnings + next steps. "
        "Snap every target / strategy / kind to the controlled vocabulary."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    imports = knowledge.get("imports") or []
    filenames = {p["filename"] for p in imports}
    target_fields = set(TARGET_FIELDS_IN_SCOPE)
    strategies = set(MERGE_STRATEGIES_IN_SCOPE)
    kinds = set(INPUT_KINDS_IN_SCOPE)
    existing_brief = knowledge.get("existing", {}).get("brief") or {}

    out: dict[str, list[Any]] = {
        "missing_input_summary": [],
        "extra_input_summary": [],
        "bad_input_kind": [],
        "input_summary_field_mismatch": [],
        "missing_extraction": [],
        "extra_extraction": [],
        "bad_target_field": [],
        "bad_confidence": [],
        "bad_conflict_target": [],
        "bad_strategy": [],
        "missing_review_for_conflict": [],
        "bad_merge_strategy": [],
        "merge_target_not_in_scope": [],
        "missing_importer_warning": [],
        "header_count_mismatch": [],
    }

    header = spec.get("header") or {}
    if (header.get("import_count") or 0) != len(imports):
        out["header_count_mismatch"].append({
            "expected": len(imports), "actual": header.get("import_count"),
        })

    # input_summary covers every parsed import.
    summary = spec.get("input_summary") or []
    seen_files: set[str] = set()
    by_filename = {p["filename"]: p for p in imports}
    for entry in summary:
        f = entry.get("filename")
        if f not in filenames:
            out["extra_input_summary"].append(f or "<missing>")
            continue
        seen_files.add(f)
        canonical = by_filename[f]
        for field in ("format", "size_bytes", "summary"):
            if entry.get(field) != canonical.get(field):
                out["input_summary_field_mismatch"].append({
                    "filename": f, "field": field,
                    "expected": canonical.get(field), "actual": entry.get(field),
                })
        if entry.get("input_kind") not in kinds:
            out["bad_input_kind"].append({
                "filename": f, "kind": entry.get("input_kind"),
            })
    for f in filenames - seen_files:
        out["missing_input_summary"].append(f)

    # Extractions cover every imported file.
    extractions = spec.get("extractions") or []
    seen_extr_files: set[str] = set()
    for ex in extractions:
        f = ex.get("source_filename")
        if f not in filenames:
            out["extra_extraction"].append(f or "<missing>")
            continue
        seen_extr_files.add(f)
        for df in ex.get("detected_fields") or []:
            if df.get("target") not in target_fields:
                out["bad_target_field"].append({
                    "filename": f, "target": df.get("target"),
                })
            if (df.get("confidence") or "").lower() not in {"high", "medium", "low"}:
                out["bad_confidence"].append({
                    "filename": f, "value": df.get("confidence"),
                })
    for f in filenames - seen_extr_files:
        out["missing_extraction"].append(f)

    # Conflicts.
    conflicts = spec.get("conflicts") or []
    conflict_targets: set[str] = set()
    for c in conflicts:
        target = c.get("target")
        if target not in target_fields:
            out["bad_conflict_target"].append(target or "<missing>")
        if (c.get("recommended_strategy") or "") not in strategies:
            out["bad_strategy"].append({
                "target": target, "strategy": c.get("recommended_strategy"),
            })
        conflict_targets.add(target)

    # Merge plan.
    merge_plan = spec.get("merge_plan") or []
    seen_merge_targets: set[str] = set()
    for entry in merge_plan:
        target = entry.get("target")
        strat = (entry.get("strategy") or "").lower()
        if target not in target_fields:
            out["merge_target_not_in_scope"].append(target or "<missing>")
        if strat not in strategies:
            out["bad_merge_strategy"].append({
                "target": target, "strategy": entry.get("strategy"),
            })
        seen_merge_targets.add(target)

    # Every conflict target must appear in the merge plan as 'review' OR
    # carry the same strategy declared in the conflict entry.
    for c in conflicts:
        target = c.get("target")
        if target not in seen_merge_targets:
            out["missing_review_for_conflict"].append(target)

    # Importer warnings — every warning string in imports[].warnings must surface.
    seen_warnings = set(spec.get("warnings") or [])
    for p in imports:
        for w in p.get("warnings") or []:
            if w not in seen_warnings:
                out["missing_importer_warning"].append({
                    "filename": p.get("filename"), "warning": w,
                })

    return {
        "input_summary_covers_every_import": not out["missing_input_summary"],
        "missing_input_summary": out["missing_input_summary"],
        "no_extra_input_summary": not out["extra_input_summary"],
        "extra_input_summary": out["extra_input_summary"],
        "input_kinds_in_scope": not out["bad_input_kind"],
        "bad_input_kind": out["bad_input_kind"],
        "input_summary_fields_match_parsed": not out["input_summary_field_mismatch"],
        "input_summary_field_mismatch": out["input_summary_field_mismatch"],
        "extractions_cover_every_import": not out["missing_extraction"],
        "missing_extraction": out["missing_extraction"],
        "no_extra_extraction": not out["extra_extraction"],
        "extra_extraction": out["extra_extraction"],
        "target_fields_in_scope": not out["bad_target_field"],
        "bad_target_field": out["bad_target_field"],
        "confidence_values_valid": not out["bad_confidence"],
        "bad_confidence": out["bad_confidence"],
        "conflict_targets_in_scope": not out["bad_conflict_target"],
        "bad_conflict_target": out["bad_conflict_target"],
        "conflict_strategies_in_scope": not out["bad_strategy"],
        "bad_conflict_strategy": out["bad_strategy"],
        "every_conflict_in_merge_plan": not out["missing_review_for_conflict"],
        "missing_review_for_conflict": out["missing_review_for_conflict"],
        "merge_strategies_in_scope": not out["bad_merge_strategy"],
        "bad_merge_strategy": out["bad_merge_strategy"],
        "merge_targets_in_scope": not out["merge_target_not_in_scope"],
        "merge_target_not_in_scope": out["merge_target_not_in_scope"],
        "all_importer_warnings_surfaced": not out["missing_importer_warning"],
        "missing_importer_warning": out["missing_importer_warning"],
        "header_count_matches_imports": not out["header_count_mismatch"],
        "header_count_mismatch": out["header_count_mismatch"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class ImportAdvisorError(RuntimeError):
    """Raised when the LLM import-advisor stage cannot produce a grounded sheet."""


async def generate_import_manifest(req: ImportAdvisorRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ImportAdvisorError(
            "OpenAI API key is not configured. The import advisor stage requires "
            "a live LLM call; no static fallback is served."
        )
    if not req.imports:
        raise ImportAdvisorError("No imports provided — at least one parsed file is required.")

    knowledge = build_import_advisor_knowledge(req)
    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": IMPORT_ADVISOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": IMPORT_ADVISOR_SCHEMA,
            },
            temperature=0.2,
            max_tokens=2800,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for import advisor")
        raise ImportAdvisorError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ImportAdvisorError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)
    return {
        "id": "import_manifest",
        "name": "Import Manifest",
        "model": settings.openai_model,
        "knowledge": knowledge,
        "import_manifest": spec,
        "validation": validation,
    }
