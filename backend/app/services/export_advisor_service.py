"""LLM-driven Export Advisor (BRD Layer 5A).

Authors a real practice-grade *export manifest* — the document that
tells the studio PM which file to send to which downstream party
(architect, fabricator, rendering studio, BIM consultant, CNC shop,
client) and what each format actually contains.

Pipeline contract — same as every other LLM service:

    INPUT (project meta + recipient list + downstream-tool list +
           bundle readiness flags)
      → INJECT  (BRD format catalogue — capabilities, precision,
                 compatible software, when-to-use, file extension,
                 readiness preconditions; current bundle's actual
                 readiness for each format)
      → LLM CALL  (live OpenAI; no static fallback)
      → VALIDATE  (every recommended format is in the registered
                 exporter catalogue; readiness flags consistent with
                 bundle state; at least one format per requested
                 recipient)
      → OUTPUT  (export_manifest JSON — recommendations + readiness
                 + per-format capability sheet)

The deterministic exporters (PDF / DXF / IFC / STEP / IGES / FBX /
GLTF / OBJ / GeoJSON / GCODE / XLSX / DOCX) live in
`app.services.exporters` and remain the source of truth for what a
file will actually contain. This service writes the cover letter, not
the file.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from app.config import get_settings
from app.services.exporters import available_formats

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


# ── Format catalogue (BRD 5A — the canonical export catalogue) ──────────────
#
# Every key MUST also be present in `app.services.exporters._REGISTRY`. The
# advisor does not invent formats — it picks from this catalogue.

FORMAT_CATALOGUE: dict[str, dict[str, Any]] = {
    "pdf": {
        "family": "document",
        "label": "PDF dossier",
        "extension": ".pdf",
        "contents": [
            "Technical drawings (plan, elevation, section, isometric)",
            "Material + manufacturing specifications",
            "Cost estimate",
            "Assembly / installation notes",
        ],
        "compatible_with": ["any reader", "Adobe Acrobat", "Preview", "browser"],
        "best_for": ["client presentation", "site office reference", "print-ready dossier"],
        "precision": "print-ready, vector + embedded raster",
        "preconditions": ["meta", "material", "manufacturing", "cost"],
    },
    "docx": {
        "family": "document",
        "label": "Word dossier",
        "extension": ".docx",
        "contents": [
            "Specifications, narrative, schedules in editable form",
            "Tables for material / labour / cost line items",
        ],
        "compatible_with": ["MS Word", "Pages", "LibreOffice", "Google Docs"],
        "best_for": ["client edits", "PM markup", "specification re-mixing"],
        "precision": "text + tables; not dimensional",
        "preconditions": ["meta", "material"],
    },
    "xlsx": {
        "family": "document",
        "label": "Spreadsheet schedule",
        "extension": ".xlsx",
        "contents": ["Bill of quantities", "Cost rollup", "Lead-time matrix"],
        "compatible_with": ["MS Excel", "Numbers", "LibreOffice", "Google Sheets"],
        "best_for": ["procurement", "cost negotiation", "schedule tracking"],
        "precision": "tabular numeric",
        "preconditions": ["material", "cost"],
    },
    "pptx": {
        "family": "document",
        "label": "PowerPoint presentation",
        "extension": ".pptx",
        "contents": [
            "Cover, concept, specification summary slides",
            "Cost & timeline overview slides",
            "Drawings/renders index, next-steps slide",
        ],
        "compatible_with": ["MS PowerPoint", "Keynote", "LibreOffice Impress", "Google Slides"],
        "best_for": ["client presentation", "design review meeting", "investor pitch"],
        "precision": "narrative deck — not dimensional",
        "preconditions": ["meta", "material", "cost"],
    },
    "html": {
        "family": "interactive",
        "label": "Interactive web viewer (HTML)",
        "extension": ".html",
        "contents": [
            "Tabbed online specification viewer",
            "Embedded 3D model viewer (model-viewer + GLTF)",
            "Client-side cost calculator (BRD bands)",
            "Customization options interface, shareable link",
        ],
        "compatible_with": ["any modern browser", "client portals", "static hosting"],
        "best_for": ["client review link", "shareable deliverable", "online specification"],
        "precision": "interactive; calculator runs entirely client-side",
        "preconditions": ["meta", "material", "cost"],
    },
    "dxf": {
        "family": "cad_2d",
        "label": "AutoCAD drawing exchange",
        "extension": ".dxf",
        "contents": [
            "2D plans, elevations, sections",
            "Dimensions, annotations, hatching, layers",
        ],
        "compatible_with": ["AutoCAD", "DraftSight", "BricsCAD", "QCAD", "LibreCAD"],
        "best_for": ["architect markup", "shopfit drawings", "site marking"],
        "precision": "scalable vector — millimetre",
        "preconditions": ["meta"],
    },
    "obj": {
        "family": "3d_mesh",
        "label": "Wavefront OBJ + MTL",
        "extension": ".obj.zip",
        "contents": ["Full 3D geometry", "Per-material colours via MTL"],
        "compatible_with": ["Blender", "SketchUp", "Rhino", "Cinema 4D", "MeshLab"],
        "best_for": ["render-ready handoff", "viz studio", "academic toolchains"],
        "precision": "polygon mesh — floor-up coordinates",
        "preconditions": ["meta"],
    },
    "gltf": {
        "family": "3d_mesh",
        "label": "glTF scene",
        "extension": ".gltf",
        "contents": ["Web-friendly 3D scene", "Embedded materials + colours"],
        "compatible_with": ["model-viewer", "Three.js", "Blender", "Babylon.js"],
        "best_for": ["client preview in browser", "AR/VR pipelines", "web embeds"],
        "precision": "polygon mesh, PBR materials",
        "preconditions": ["meta"],
    },
    "fbx": {
        "family": "3d_mesh",
        "label": "Autodesk FBX (ASCII 7.4)",
        "extension": ".fbx.zip",
        "contents": ["Full 3D geometry with materials", "Schedulable nodes"],
        "compatible_with": ["3ds Max", "Maya", "Blender", "MotionBuilder", "Unity", "Unreal"],
        "best_for": ["rendering studio handoff", "real-time engines"],
        "precision": "polygon mesh — Y-up, centimetre scale unit",
        "preconditions": ["meta"],
    },
    "ifc": {
        "family": "bim",
        "label": "IFC4 (Industry Foundation Classes)",
        "extension": ".ifc",
        "contents": [
            "Parametric 3D model with materials",
            "Schedulable building components",
            "Cost data + property sets linked",
        ],
        "compatible_with": ["Revit", "ArchiCAD", "Vectorworks", "Solibri", "BIMcollab"],
        "best_for": ["BIM coordination", "owner handover", "FM platforms"],
        "precision": "ISO 16739 — parametric; millimetre",
        "preconditions": ["meta", "material", "cost"],
    },
    "step": {
        "family": "cad_3d",
        "label": "STEP AP214 (ISO-10303)",
        "extension": ".step",
        "contents": ["Parametric solid B-rep", "Manufacturing-ready geometry"],
        "compatible_with": ["FreeCAD", "Fusion 360", "SolidWorks", "OnShape", "Siemens NX", "CATIA"],
        "best_for": ["CNC / CAM input", "fabricator's CAD seat", "tooling"],
        "precision": "±0.1 mm; ISO-10303 solid model",
        "preconditions": ["meta"],
    },
    "iges": {
        "family": "cad_3d",
        "label": "IGES 5.3",
        "extension": ".igs",
        "contents": ["Faceted geometry — legacy CAD exchange"],
        "compatible_with": ["legacy CATIA / Pro-E / NX seats", "FreeCAD"],
        "best_for": ["CAD systems that prefer IGES over STEP"],
        "precision": "millimetre",
        "preconditions": ["meta"],
    },
    "gcode": {
        "family": "cnc",
        "label": "G-code (RS-274) — nested routing program",
        "extension": ".gcode",
        "contents": [
            "Nested CNC routing program (T1 contour + T2 rebate + T3 pilot holes)",
            "Sheet utilisation summary in the file header",
            "Tool catalogue (slot / diameter / rpm / feed / plunge)",
        ],
        "compatible_with": ["Mach3", "LinuxCNC", "GRBL", "Fanuc", "Haas"],
        "best_for": ["direct router / mill handoff for first-stage cuts"],
        "precision": "tool-radius compensated; millimetre; ±0.1 mm",
        "preconditions": ["meta"],
    },
    "cam_prep": {
        "family": "cnc",
        "label": "CAM prep bundle (zip)",
        "extension": ".zip",
        "contents": [
            "1:1 SVG cutting pattern (laser / waterjet / CNC / plotter)",
            "Machine-readable nesting JSON with sheet utilisation",
            "Quality checkpoints CSV (sequenced from manufacturing spec)",
            "Sequential assembly CSV (steps, tools, torques)",
            "Tool specifications CSV matching the G-code header",
        ],
        "compatible_with": ["Adobe Illustrator", "RDWorks", "LightBurn", "Fusion 360 CAM", "VCarve", "shop-floor printers"],
        "best_for": ["fabricator handoff", "shop-floor printout", "QA station setup"],
        "precision": "1:1 mm vector; CSV / JSON",
        "preconditions": ["meta"],
    },
    "geojson": {
        "family": "data",
        "label": "GeoJSON FeatureCollection",
        "extension": ".geojson",
        "contents": [
            "Top-down plan as polygon features",
            "Per-feature metadata (material, finish, manufacturing, cost, schedule)",
        ],
        "compatible_with": ["QGIS", "ArcGIS", "Mapbox", "Leaflet", "BIM ingestion pipelines"],
        "best_for": ["project-management dashboards", "BIM data overlay", "GIS tooling"],
        "precision": "RFC 7946; local Cartesian metres",
        "preconditions": ["meta"],
    },
}


# Recipient roles → which format families typically apply.
RECIPIENT_FAMILIES: dict[str, tuple[str, ...]] = {
    "client":               ("document", "3d_mesh", "interactive"),
    "architect":            ("cad_2d", "bim", "document"),
    "interior_designer":    ("3d_mesh", "document", "data", "interactive"),
    "fabricator":           ("cad_3d", "cnc", "document"),
    "cnc_shop":             ("cnc", "cad_3d"),
    "rendering_studio":     ("3d_mesh",),
    "bim_consultant":       ("bim", "data"),
    "project_manager":      ("document", "data", "interactive"),
    "structural_engineer":  ("cad_2d", "cad_3d", "bim"),
    "mep_consultant":       ("cad_2d", "bim", "document"),
}


# ── Request schema ──────────────────────────────────────────────────────────


class ExportAdvisorRequest(BaseModel):
    project_name: str = Field(default="KATHA Project", max_length=200)
    piece_name: str = Field(default="Primary piece", max_length=160)
    theme: str = Field(default="", max_length=64)
    recipients: list[str] = Field(
        default_factory=lambda: ["client", "fabricator", "architect"],
    )
    downstream_software: list[str] = Field(default_factory=list)
    bundle_status: dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Readiness flags from the spec bundle — keys: meta, material, "
            "manufacturing, cost, mep. Missing keys default to false."
        ),
    )
    notes: str = Field(default="", max_length=600)


# ── Knowledge slice ─────────────────────────────────────────────────────────


def _format_readiness(req: ExportAdvisorRequest) -> dict[str, Any]:
    """Per-format readiness based on bundle status flags."""
    bundle = {k: bool(v) for k, v in (req.bundle_status or {}).items()}
    out: dict[str, dict[str, Any]] = {}
    for key, spec in FORMAT_CATALOGUE.items():
        unmet = [pre for pre in spec["preconditions"] if not bundle.get(pre)]
        out[key] = {
            "ready": not unmet,
            "missing_preconditions": unmet,
        }
    return out


def build_export_advisor_knowledge(req: ExportAdvisorRequest) -> dict[str, Any]:
    registered = set(available_formats())
    catalogue_in_scope = {k: v for k, v in FORMAT_CATALOGUE.items() if k in registered}
    return {
        "project": {
            "name": req.project_name,
            "piece_name": req.piece_name,
            "theme": req.theme or None,
            "recipients": list(req.recipients or []),
            "downstream_software": list(req.downstream_software or []),
            "notes": req.notes or None,
        },
        "format_catalogue": catalogue_in_scope,
        "registered_format_keys": sorted(registered),
        "recipient_families": {
            r: list(RECIPIENT_FAMILIES.get(r, ()))
            for r in (req.recipients or [])
        },
        "recipient_roles_in_scope": list(RECIPIENT_FAMILIES.keys()),
        "format_readiness": _format_readiness(req),
        "bundle_status": {
            k: bool(v) for k, v in (req.bundle_status or {}).items()
        },
    }


# ── System prompt ───────────────────────────────────────────────────────────


EXPORT_ADVISOR_SYSTEM_PROMPT = """You are a senior studio principal authoring the *Export Manifest* (BRD Layer 5A) — the cover letter that tells the project team which file goes to which downstream party.

Read the [KNOWLEDGE] block — format_catalogue (PDF / DOCX / XLSX / DXF / OBJ / GLTF / FBX / IFC / STEP / IGES / GCODE / GeoJSON; each with contents / compatible_with / best_for / precision / preconditions), recipient_families (which format families fit which recipient role), format_readiness (which formats are ready given the current bundle), and the project recipients list — and produce a structured export_manifest JSON.

Studio voice — short, decisive, no marketing prose. You DO NOT generate the files; you list them and say what each one does.

Hard rules for header:
- bundle_summary MUST mirror knowledge.bundle_status verbatim (booleans).

Hard rules for format_catalogue (one entry per format key):
- format_key MUST be in registered_format_keys.
- label, extension, family, contents, compatible_with, best_for, precision MUST equal format_catalogue[format_key] verbatim — do NOT paraphrase.
- ready MUST equal format_readiness[format_key].ready.
- missing_preconditions MUST equal format_readiness[format_key].missing_preconditions verbatim.
- The list MUST cover every key in registered_format_keys.

Hard rules for recipient_recommendations (one entry per requested recipient):
- recipient MUST be in recipient_roles_in_scope.
- Each entry's recommended_formats[] is an ordered list (most-relevant first) of format_keys from registered_format_keys whose family appears in recipient_families[recipient].
- Each recommended format MUST also be 'ready' in format_readiness; if no ready formats apply for a recipient, set recommended_formats=[] and explain in rationale (e.g. "BIM consultant requires IFC, which needs the cost block — ship after 4A is complete").
- Each entry's must_include[] cites 1–3 contents bullets from the catalogue (verbatim) that this recipient relies on.
- Each entry's rationale (one short sentence) explains WHY these formats fit the recipient's workflow — cite the compatible_with software the recipient is most likely using.

Hard rules for handoff_pack (the final shortlist):
- primary_format MUST be a recommended format that is ready and applies to AT LEAST one requested recipient.
- supplementary_formats[] is a deduped list of additional ready formats across recipients.
- combined_archive_recommended MUST be true when supplementary_formats has 2+ entries (one zip per project handoff).

Hard rules for warnings:
- Emit one warning per format whose ready=false AND that the recipient list would otherwise need (e.g. "STEP not ready — fabricator handoff blocked: bundle missing meta").
- Emit a warning if a recipient is in recipient_roles_in_scope but no compatible family is registered (e.g. "no CNC format in registry → cnc_shop has no recommendation").

Never invent formats, recipients, software names, or precision claims. Snap every label and capability to format_catalogue."""


# ── JSON schema ─────────────────────────────────────────────────────────────


def _format_entry_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "format_key": {"type": "string"},
            "label": {"type": "string"},
            "extension": {"type": "string"},
            "family": {"type": "string"},
            "contents": {"type": "array", "items": {"type": "string"}},
            "compatible_with": {"type": "array", "items": {"type": "string"}},
            "best_for": {"type": "array", "items": {"type": "string"}},
            "precision": {"type": "string"},
            "ready": {"type": "boolean"},
            "missing_preconditions": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "format_key", "label", "extension", "family",
            "contents", "compatible_with", "best_for", "precision",
            "ready", "missing_preconditions",
        ],
        "additionalProperties": False,
    }


def _recipient_entry_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "recipient": {"type": "string"},
            "recommended_formats": {
                "type": "array",
                "items": {"type": "string"},
            },
            "must_include": {"type": "array", "items": {"type": "string"}},
            "rationale": {"type": "string"},
        },
        "required": [
            "recipient", "recommended_formats", "must_include", "rationale",
        ],
        "additionalProperties": False,
    }


EXPORT_ADVISOR_SCHEMA: dict[str, Any] = {
    "name": "export_manifest",
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
                    "date_iso": {"type": "string"},
                    "bundle_summary": {
                        "type": "object",
                        "properties": {
                            "meta": {"type": "boolean"},
                            "material": {"type": "boolean"},
                            "manufacturing": {"type": "boolean"},
                            "cost": {"type": "boolean"},
                            "mep": {"type": "boolean"},
                        },
                        "required": ["meta", "material", "manufacturing", "cost", "mep"],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "project", "piece_name", "theme",
                    "date_iso", "bundle_summary",
                ],
                "additionalProperties": False,
            },
            "format_catalogue": {
                "type": "array",
                "items": _format_entry_schema(),
            },
            "recipient_recommendations": {
                "type": "array",
                "items": _recipient_entry_schema(),
            },
            "handoff_pack": {
                "type": "object",
                "properties": {
                    "primary_format": {"type": "string"},
                    "supplementary_formats": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "combined_archive_recommended": {"type": "boolean"},
                    "rationale": {"type": "string"},
                },
                "required": [
                    "primary_format", "supplementary_formats",
                    "combined_archive_recommended", "rationale",
                ],
                "additionalProperties": False,
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "assumptions": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "header", "format_catalogue", "recipient_recommendations",
            "handoff_pack", "warnings", "assumptions",
        ],
        "additionalProperties": False,
    },
}


def _user_message(req: ExportAdvisorRequest, knowledge: dict[str, Any]) -> str:
    today = datetime.now(timezone.utc).date().isoformat()
    return (
        "[KNOWLEDGE]\n" + json.dumps(knowledge, indent=2, default=str) + "\n\n"
        "[BRIEF]\n"
        f"- Project: {req.project_name}\n"
        f"- Piece: {req.piece_name}\n"
        f"- Theme: {req.theme or '(not specified)'}\n"
        f"- Recipients: {', '.join(req.recipients)}\n"
        f"- Downstream software: {', '.join(req.downstream_software) or '(none stated)'}\n"
        f"- Date (UTC ISO): {today}\n"
        f"- Notes: {req.notes or '(none)'}\n\n"
        "Produce the export_manifest JSON. List every registered format "
        "with its catalogue capabilities + readiness. Make a recipient "
        "shortlist for each requested recipient. Pick a primary handoff "
        "format and supplementary formats. Snap every label, extension, "
        "and capability to the catalogue verbatim — never paraphrase."
    )


# ── Validation ──────────────────────────────────────────────────────────────


def _validate(spec: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    catalogue = knowledge.get("format_catalogue") or {}
    registered = set(knowledge.get("registered_format_keys") or [])
    readiness = knowledge.get("format_readiness") or {}
    recipients = list((knowledge.get("project") or {}).get("recipients") or [])
    recipient_families = knowledge.get("recipient_families") or {}
    bundle_status = knowledge.get("bundle_status") or {}

    out: dict[str, list[Any]] = {
        "missing_format_in_catalogue": [],
        "extra_format_in_catalogue": [],
        "format_field_mismatch": [],
        "format_readiness_mismatch": [],
        "missing_recipient_entry": [],
        "extra_recipient_entry": [],
        "recommended_format_unknown": [],
        "recommended_format_wrong_family": [],
        "recommended_format_not_ready": [],
        "primary_not_in_registry": [],
        "primary_not_ready": [],
        "primary_not_used_by_any_recipient": [],
        "bundle_summary_mismatch": [],
    }

    # Header bundle summary.
    header = spec.get("header") or {}
    summary = header.get("bundle_summary") or {}
    for key in ("meta", "material", "manufacturing", "cost", "mep"):
        expected = bool(bundle_status.get(key, False))
        actual = bool(summary.get(key, False))
        if expected != actual:
            out["bundle_summary_mismatch"].append({
                "field": key, "expected": expected, "actual": actual,
            })

    # Format catalogue.
    catalogue_block = spec.get("format_catalogue") or []
    seen_keys: set[str] = set()
    for entry in catalogue_block:
        key = entry.get("format_key")
        if key not in registered:
            out["extra_format_in_catalogue"].append(key or "<missing>")
            continue
        seen_keys.add(key)
        canonical = catalogue.get(key) or {}
        for field in ("label", "extension", "family", "precision"):
            if entry.get(field) != canonical.get(field):
                out["format_field_mismatch"].append({
                    "key": key, "field": field,
                    "expected": canonical.get(field), "actual": entry.get(field),
                })
        for arr_field in ("contents", "compatible_with", "best_for"):
            if list(entry.get(arr_field) or []) != list(canonical.get(arr_field) or []):
                out["format_field_mismatch"].append({
                    "key": key, "field": arr_field,
                    "expected": canonical.get(arr_field), "actual": entry.get(arr_field),
                })
        # Readiness.
        rstate = readiness.get(key) or {}
        if bool(entry.get("ready")) != bool(rstate.get("ready")):
            out["format_readiness_mismatch"].append({
                "key": key, "field": "ready",
                "expected": rstate.get("ready"), "actual": entry.get("ready"),
            })
        if list(entry.get("missing_preconditions") or []) != list(rstate.get("missing_preconditions") or []):
            out["format_readiness_mismatch"].append({
                "key": key, "field": "missing_preconditions",
                "expected": rstate.get("missing_preconditions"),
                "actual": entry.get("missing_preconditions"),
            })

    for key in registered - seen_keys:
        out["missing_format_in_catalogue"].append(key)

    # Recipient recommendations.
    rec_block = spec.get("recipient_recommendations") or []
    seen_recipients: set[str] = set()
    for entry in rec_block:
        recipient = entry.get("recipient")
        if recipient not in recipients:
            out["extra_recipient_entry"].append(recipient or "<missing>")
            continue
        seen_recipients.add(recipient)
        allowed_families = set(recipient_families.get(recipient) or [])
        for fmt_key in entry.get("recommended_formats") or []:
            if fmt_key not in registered:
                out["recommended_format_unknown"].append({
                    "recipient": recipient, "format_key": fmt_key,
                })
                continue
            family = (catalogue.get(fmt_key) or {}).get("family")
            if allowed_families and family not in allowed_families:
                out["recommended_format_wrong_family"].append({
                    "recipient": recipient, "format_key": fmt_key,
                    "family": family, "allowed": list(allowed_families),
                })
            if not (readiness.get(fmt_key) or {}).get("ready"):
                out["recommended_format_not_ready"].append({
                    "recipient": recipient, "format_key": fmt_key,
                    "missing": (readiness.get(fmt_key) or {}).get("missing_preconditions"),
                })

    for r in recipients:
        if r not in seen_recipients:
            out["missing_recipient_entry"].append(r)

    # Handoff pack.
    pack = spec.get("handoff_pack") or {}
    primary = pack.get("primary_format")
    if primary not in registered:
        out["primary_not_in_registry"].append(primary or "<missing>")
    elif not (readiness.get(primary) or {}).get("ready"):
        out["primary_not_ready"].append({
            "primary": primary,
            "missing": (readiness.get(primary) or {}).get("missing_preconditions"),
        })
    else:
        family = (catalogue.get(primary) or {}).get("family")
        used = any(
            family in (recipient_families.get(r) or ())
            for r in recipients
        )
        if recipients and not used:
            out["primary_not_used_by_any_recipient"].append({
                "primary": primary, "family": family,
            })

    return {
        "every_registered_format_listed": not out["missing_format_in_catalogue"],
        "missing_format_in_catalogue": out["missing_format_in_catalogue"],
        "no_extra_formats_listed": not out["extra_format_in_catalogue"],
        "extra_format_in_catalogue": out["extra_format_in_catalogue"],
        "format_fields_match_catalogue": not out["format_field_mismatch"],
        "format_field_mismatch": out["format_field_mismatch"],
        "format_readiness_matches_bundle": not out["format_readiness_mismatch"],
        "format_readiness_mismatch": out["format_readiness_mismatch"],
        "every_requested_recipient_present": not out["missing_recipient_entry"],
        "missing_recipient_entry": out["missing_recipient_entry"],
        "no_extra_recipient_entries": not out["extra_recipient_entry"],
        "extra_recipient_entry": out["extra_recipient_entry"],
        "recommended_formats_in_registry": not out["recommended_format_unknown"],
        "recommended_format_unknown": out["recommended_format_unknown"],
        "recommended_formats_match_recipient_family": not out["recommended_format_wrong_family"],
        "recommended_format_wrong_family": out["recommended_format_wrong_family"],
        "recommended_formats_are_ready": not out["recommended_format_not_ready"],
        "recommended_format_not_ready": out["recommended_format_not_ready"],
        "primary_format_in_registry": not out["primary_not_in_registry"],
        "primary_not_in_registry": out["primary_not_in_registry"],
        "primary_format_is_ready": not out["primary_not_ready"],
        "primary_not_ready": out["primary_not_ready"],
        "primary_format_used_by_a_recipient": not out["primary_not_used_by_any_recipient"],
        "primary_not_used_by_any_recipient": out["primary_not_used_by_any_recipient"],
        "bundle_summary_matches_input": not out["bundle_summary_mismatch"],
        "bundle_summary_mismatch": out["bundle_summary_mismatch"],
    }


# ── Public API ──────────────────────────────────────────────────────────────


class ExportAdvisorError(RuntimeError):
    """Raised when the LLM export-advisor stage cannot produce a grounded sheet."""


async def generate_export_manifest(req: ExportAdvisorRequest) -> dict[str, Any]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ExportAdvisorError(
            "OpenAI API key is not configured. The export advisor stage requires "
            "a live LLM call; no static fallback is served."
        )

    bad_recipients = [
        r for r in (req.recipients or []) if r not in RECIPIENT_FAMILIES
    ]
    if bad_recipients:
        raise ExportAdvisorError(
            f"Unknown recipient role(s): {', '.join(bad_recipients)}. "
            f"Pick from: {', '.join(sorted(RECIPIENT_FAMILIES.keys()))}."
        )

    knowledge = build_export_advisor_knowledge(req)
    user_message = _user_message(req, knowledge)
    client = _client_instance()

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": EXPORT_ADVISOR_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": EXPORT_ADVISOR_SCHEMA,
            },
            temperature=0.2,
            max_tokens=2400,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("LLM call failed for export advisor")
        raise ExportAdvisorError(f"LLM call failed: {exc}") from exc

    raw = response.choices[0].message.content or "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ExportAdvisorError("LLM returned malformed JSON") from exc

    validation = _validate(spec, knowledge)

    return {
        "id": "export_manifest",
        "name": "Export Manifest",
        "model": settings.openai_model,
        "knowledge": knowledge,
        "export_manifest": spec,
        "validation": validation,
    }
