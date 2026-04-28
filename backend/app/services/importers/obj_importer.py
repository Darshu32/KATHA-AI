"""OBJ / GLTF / FBX importer — bounding box + material list.

OBJ is plain text — we parse `v` (vertex) and `usemtl` lines to derive
a scene bounding box and the material catalogue.

GLTF (JSON) and FBX (ASCII) emit a smaller payload — we surface what
we can find in the headers and emit a warning for anything that needs
a full mesh kernel.
"""

from __future__ import annotations

import json
import re
from typing import Any


_GROUP_RE = re.compile(r"^[og]\s+(\S+)", re.MULTILINE)
_MTL_RE = re.compile(r"^usemtl\s+(\S+)", re.MULTILINE)


def _parse_obj(text: str) -> dict[str, Any]:
    xs: list[float] = []; ys: list[float] = []; zs: list[float] = []
    for line in text.splitlines():
        if line.startswith("v "):
            try:
                _, x, y, z, *_ = line.split()
                xs.append(float(x)); ys.append(float(y)); zs.append(float(z))
            except ValueError:
                continue
    bbox = None
    if xs:
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
    groups = sorted(set(m.group(1) for m in _GROUP_RE.finditer(text)))
    mats = sorted(set(m.group(1) for m in _MTL_RE.finditer(text)))
    return {
        "vertex_count": len(xs),
        "group_count": len(groups),
        "groups": groups[:50],
        "materials": mats,
        "bbox": bbox,
    }


def _parse_gltf(text: str) -> dict[str, Any]:
    try:
        gltf = json.loads(text)
    except json.JSONDecodeError:
        return {"warnings": ["GLTF JSON malformed."]}
    return {
        "asset_version": (gltf.get("asset") or {}).get("version"),
        "generator": (gltf.get("asset") or {}).get("generator"),
        "node_count": len(gltf.get("nodes") or []),
        "mesh_count": len(gltf.get("meshes") or []),
        "material_count": len(gltf.get("materials") or []),
        "materials": [m.get("name") for m in (gltf.get("materials") or []) if m.get("name")],
    }


def _parse_fbx_ascii(text: str) -> dict[str, Any]:
    models = re.findall(r'Model:\s+\d+,\s*"Model::([^"]+)"', text)
    materials = re.findall(r'Material:\s+\d+,\s*"Material::([^"]+)"', text)
    return {
        "model_count": len(models),
        "models": models[:50],
        "materials": sorted(set(materials)),
    }


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    ext = filename.rsplit(".", 1)[-1].lower()
    text = payload.decode("utf-8", errors="ignore")
    warnings: list[str] = []

    if ext == "obj":
        info = _parse_obj(text)
        extent = (info.get("bbox") or {}).get("extent_m") or []
        return {
            "format": "obj",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": (
                f"OBJ: {info['vertex_count']} vertices; {info['group_count']} group(s); "
                f"{len(info['materials'])} material(s)"
                + (f"; extent {extent[0]:.2f} × {extent[1]:.2f} × {extent[2]:.2f}"
                   if extent and all(e is not None for e in extent) else "")
            ),
            "extracted": info,
            "warnings": warnings,
        }
    if ext == "gltf":
        info = _parse_gltf(text)
        return {
            "format": "gltf",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": (
                f"GLTF {info.get('asset_version','?')}: "
                f"{info.get('mesh_count',0)} mesh(es), "
                f"{info.get('material_count',0)} material(s)."
            ),
            "extracted": info,
            "warnings": warnings + (info.get("warnings") or []),
        }
    if ext == "fbx":
        if not text.lstrip().startswith(";") and "FBX" not in text[:200]:
            warnings.append(
                "Binary FBX detected — only ASCII FBX is parsed by this importer."
            )
            return {
                "format": "fbx",
                "filename": filename,
                "size_bytes": len(payload),
                "summary": "Binary FBX cannot be parsed without the Autodesk SDK.",
                "extracted": {},
                "warnings": warnings,
            }
        info = _parse_fbx_ascii(text)
        return {
            "format": "fbx",
            "filename": filename,
            "size_bytes": len(payload),
            "summary": (
                f"FBX (ASCII): {info['model_count']} model(s); "
                f"{len(info['materials'])} material(s)."
            ),
            "extracted": info,
            "warnings": warnings,
        }

    return {
        "format": ext,
        "filename": filename,
        "size_bytes": len(payload),
        "summary": "Unsupported 3D extension.",
        "extracted": {},
        "warnings": [f"No 3D parser registered for '.{ext}'."],
    }
