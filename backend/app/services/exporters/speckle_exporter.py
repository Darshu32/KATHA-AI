"""Speckle exporter — serialized object tree as a downloadable `.speckle.json`.

Registry adapter over ``app.services.spatial.speckle_export``: unlike the naive
per-object-box exporters (obj/gltf/fbx), this carries geometry-true meshes cut
from the real Manifold kernel. The file is the exact serialized Speckle object
graph; the *live* versioned push to a Speckle server is the separate
``GET /projects/{id}/export/speckle?push=true`` route (a server commit can't be
expressed as a file download).
"""

from __future__ import annotations

import json

from app.services.spatial.speckle_export import build_speckle_base, serialize_base


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "design"


def export(spec: dict, graph: dict) -> dict:
    """Return {content_type, filename, bytes} — the serialized Speckle tree."""
    project_name = (spec.get("meta") or {}).get("project_name") or "KATHA design"
    root = build_speckle_base(graph, project_name)
    _hash, root_obj = serialize_base(root)
    payload = json.dumps(root_obj).encode("utf-8")
    return {
        "content_type": "application/json",
        "filename": f"{_safe_name(project_name)}.speckle.json",
        "bytes": payload,
    }
