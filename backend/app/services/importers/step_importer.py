"""STEP / IGES importer — header parse + bounding box from CARTESIAN_POINTs.

No CAD kernel needed: STEP is plain text. We pull the FILE_DESCRIPTION /
FILE_NAME / FILE_SCHEMA blocks for provenance, count BREP entities,
and aggregate every CARTESIAN_POINT to compute a scene bounding box
that can be mapped onto the design graph's room dimensions.

IGES is handled by the same parser — we only inspect the global section
for header metadata and do not attempt geometry parsing (legacy
fixed-width records); a warning explains the difference.
"""

from __future__ import annotations

import re
from typing import Any


_HEADER_RE = re.compile(r"FILE_(DESCRIPTION|NAME|SCHEMA)\s*\((.*?)\);", re.DOTALL)
_POINT_RE = re.compile(
    r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*([-\d\.eE+]+)\s*,\s*([-\d\.eE+]+)\s*,\s*([-\d\.eE+]+)\s*\)\s*\)",
)
_ENTITY_COUNT_RE = re.compile(r"^#\d+\s*=", re.MULTILINE)


def _parse_step(text: str) -> dict[str, Any]:
    headers = {m.group(1).lower(): m.group(2).strip() for m in _HEADER_RE.finditer(text)}
    pts = [tuple(map(float, m.groups())) for m in _POINT_RE.finditer(text)]
    entity_count = len(_ENTITY_COUNT_RE.findall(text))

    bbox = None
    if pts:
        xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
        bbox = {
            "x": [min(xs), max(xs)],
            "y": [min(ys), max(ys)],
            "z": [min(zs), max(zs)],
            "extent_m": [
                round(max(xs) - min(xs), 4),
                round(max(ys) - min(ys), 4),
                round(max(zs) - min(zs), 4),
            ],
        }
    schema = "AP214"
    if "AP242" in text:
        schema = "AP242"
    elif "AP203" in text:
        schema = "AP203"
    return {
        "schema": schema,
        "headers": headers,
        "entity_count": entity_count,
        "vertex_count": len(pts),
        "bbox": bbox,
    }


def _parse_iges(text: str) -> dict[str, Any]:
    # IGES — pull the Global (G) section, joined.
    g_lines = [ln for ln in text.splitlines() if ln[-1:] == "G"]
    g_text = "".join(ln[:72] for ln in g_lines)
    return {"global_section_excerpt": g_text[:600]}


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    text = payload.decode("latin-1", errors="ignore")
    ext = filename.rsplit(".", 1)[-1].lower()

    if ext in ("iges", "igs"):
        info = _parse_iges(text)
        return {
            "format": "iges",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": "IGES global section parsed; geometry kernel needed for full extract.",
            "extracted": info,
            "warnings": [
                "IGES geometry parsing not implemented — converting to STEP recommended."
            ],
        }

    info = _parse_step(text)
    bbox = info.get("bbox") or {}
    extent = bbox.get("extent_m") or []
    return {
        "format": "step",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"STEP {info['schema']}: {info['entity_count']} entities, "
            f"{info['vertex_count']} vertices"
            + (f"; extent {extent[0]:.2f} × {extent[1]:.2f} × {extent[2]:.2f} m"
               if extent and all(e is not None for e in extent) else "")
        ),
        "extracted": info,
        "warnings": [],
    }
