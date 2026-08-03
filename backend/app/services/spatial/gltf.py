"""Kernel solids → glTF 2.0 for the browser 3D viewport.

Emits the *real* Manifold geometry (walls, courtyard voids, furniture) as a
self-contained glTF (JSON + embedded binary buffer), flat-shaded with one
material per solid. This is what makes the workspace show a live, orbitable
model of the actual spec — not a flat image. World coordinates are Y-up
right-handed, matching glTF/three.js, so no axis flip is needed.
"""

from __future__ import annotations

import base64
import json

import numpy as np

from app.services.spatial.kernel import build_scene

_FLOAT, _UINT, _VEC3, _SCALAR = 5126, 5125, "VEC3", "SCALAR"
_ARRAY_BUFFER, _ELEMENT_ARRAY_BUFFER = 34962, 34963


def _flat_soup(verts: np.ndarray, tris: np.ndarray):
    """Expand indexed mesh into a flat-shaded soup: one triangle's three
    corners each carry that triangle's face normal (crisp architectural edges)."""
    p = verts[tris].reshape(-1, 3).astype("<f4")                       # (3M,3)
    e1 = verts[tris[:, 1]] - verts[tris[:, 0]]
    e2 = verts[tris[:, 2]] - verts[tris[:, 0]]
    fn = np.cross(e1, e2)
    norm = np.linalg.norm(fn, axis=1, keepdims=True)
    fn = np.divide(fn, norm, out=np.zeros_like(fn), where=norm > 1e-12)
    n = np.repeat(fn, 3, axis=0).astype("<f4")                         # (3M,3)
    idx = np.arange(len(p), dtype="<u4")
    return p, n, idx


def scene_to_gltf(graph: dict) -> bytes | None:
    """Build solids from the spec and serialise them to glTF bytes, or None when
    there's no geometry to show."""
    solids, _bbox, _kind = build_scene(graph)
    # Drop the exterior ground plane — it's a finish-render aid (grounds
    # shadows in the 2D pass) but in an orbit viewport its ~100 m span just
    # dwarfs the building and wrecks framing. Walls/floor (interiors) stay.
    solids = [
        s for s in solids
        if s.type != "ground" and s.verts is not None and len(s.verts)
        and s.tris is not None and len(s.tris)
    ]
    if not solids:
        return None

    binary = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []
    materials: list[dict] = []
    nodes: list[dict] = []

    def _add_view(payload: bytes, target: int) -> int:
        while len(binary) % 4:                      # 4-byte alignment
            binary.append(0)
        offset = len(binary)
        binary.extend(payload)
        buffer_views.append({"buffer": 0, "byteOffset": offset,
                             "byteLength": len(payload), "target": target})
        return len(buffer_views) - 1

    def _add_accessor(view: int, count: int, ctype: int, atype: str, mn=None, mx=None) -> int:
        acc = {"bufferView": view, "componentType": ctype, "count": count, "type": atype}
        if mn is not None:
            acc["min"], acc["max"] = mn, mx
        accessors.append(acc)
        return len(accessors) - 1

    for s in solids:
        # Place via node translation, not baked world coords: localise the
        # geometry to its own bbox centre and put that centre on the node. Then
        # the node origin sits ON the object — so an editor's transform gizmo
        # lands on it, and a drag reads back as the object's absolute position.
        center = (s.verts.min(0) + s.verts.max(0)) / 2.0
        p, n, idx = _flat_soup(s.verts - center, s.tris)
        pv = _add_view(p.tobytes(), _ARRAY_BUFFER)
        pa = _add_accessor(pv, len(p), _FLOAT, _VEC3,
                          p.min(0).tolist(), p.max(0).tolist())
        nv = _add_view(n.tobytes(), _ARRAY_BUFFER)
        na = _add_accessor(nv, len(n), _FLOAT, _VEC3)
        iv = _add_view(idx.tobytes(), _ELEMENT_ARRAY_BUFFER)
        ia = _add_accessor(iv, len(idx), _UINT, _SCALAR)

        r, g, b = s.color
        materials.append({
            "name": s.type,
            "doubleSided": True,   # so cutaway interiors read from any angle
            "pbrMetallicRoughness": {
                "baseColorFactor": [float(r), float(g), float(b), 1.0],
                "metallicFactor": 0.0, "roughnessFactor": 0.72,
            },
        })
        meshes.append({"primitives": [{
            "attributes": {"POSITION": pa, "NORMAL": na},
            "indices": ia, "material": len(materials) - 1, "mode": 4,
        }]})
        nodes.append({
            "name": s.id,
            "mesh": len(meshes) - 1,
            "translation": [float(center[0]), float(center[1]), float(center[2])],
        })

    gltf = {
        "asset": {"version": "2.0", "generator": "KATHA spatial kernel"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{
            "byteLength": len(binary),
            "uri": "data:application/octet-stream;base64," + base64.b64encode(bytes(binary)).decode("ascii"),
        }],
    }
    return json.dumps(gltf).encode("utf-8")
