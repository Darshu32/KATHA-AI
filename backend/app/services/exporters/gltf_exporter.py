"""glTF 2.0 exporter — web-native 3D scene.

Emits a single self-contained `.gltf` file (JSON) with the geometry
buffer encoded as a data URI. This opens directly in any glTF viewer:
three.js, model-viewer, Blender, Windows 3D Viewer, Babylon.js, etc.

Built with the stdlib only — no pygltflib dep. The spec is simple enough
that a direct JSON emit is more maintainable than an extra library.
"""

from __future__ import annotations

import base64
import json
import struct


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _hex_to_rgb01(value: str) -> tuple[float, float, float, float]:
    if not isinstance(value, str):
        return (0.7, 0.65, 0.55, 1.0)
    v = value.lstrip("#")
    if len(v) != 6:
        return (0.7, 0.65, 0.55, 1.0)
    try:
        return int(v[0:2], 16) / 255.0, int(v[2:4], 16) / 255.0, int(v[4:6], 16) / 255.0, 1.0
    except ValueError:
        return (0.7, 0.65, 0.55, 1.0)


# ── Box primitive ───────────────────────────────────────────────────────────
# 24 vertices (4 per face so each face gets its own normal).
def _box_vertices_normals(l: float, h: float, w: float):
    hx, hz = l / 2, w / 2
    # Per-face: 4 corners + shared normal
    faces = [
        # -Y bottom
        ([(-hx, 0, -hz), (hx, 0, -hz), (hx, 0, hz), (-hx, 0, hz)], (0, -1, 0)),
        # +Y top
        ([(-hx, h, -hz), (-hx, h, hz), (hx, h, hz), (hx, h, -hz)], (0, 1, 0)),
        # -X left
        ([(-hx, 0, -hz), (-hx, 0, hz), (-hx, h, hz), (-hx, h, -hz)], (-1, 0, 0)),
        # +X right
        ([(hx, 0, -hz), (hx, h, -hz), (hx, h, hz), (hx, 0, hz)], (1, 0, 0)),
        # -Z back
        ([(-hx, 0, -hz), (-hx, h, -hz), (hx, h, -hz), (hx, 0, -hz)], (0, 0, -1)),
        # +Z front
        ([(-hx, 0, hz), (hx, 0, hz), (hx, h, hz), (-hx, h, hz)], (0, 0, 1)),
    ]
    verts: list[tuple[float, float, float]] = []
    norms: list[tuple[float, float, float]] = []
    indices: list[int] = []
    for quad, n in faces:
        base = len(verts)
        for v in quad:
            verts.append(v)
            norms.append(n)
        indices += [base, base + 1, base + 2, base, base + 2, base + 3]
    return verts, norms, indices


def _pack_floats(data):
    flat: list[float] = []
    for tup in data:
        flat.extend(tup)
    return struct.pack(f"<{len(flat)}f", *flat)


def _pack_uints(data):
    return struct.pack(f"<{len(data)}I", *data)


def _bounds(vs):
    xs = [v[0] for v in vs]; ys = [v[1] for v in vs]; zs = [v[2] for v in vs]
    return [min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)]


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta", {})
    project_name = meta.get("project_name", "KATHA project")

    # Gather material index with colours.
    mat_index: dict[str, int] = {}
    materials: list[dict] = []
    for mat in graph.get("materials", []):
        mid = mat.get("id") or mat.get("name") or "mat"
        name = mat.get("name") or mid
        r, g, b, a = _hex_to_rgb01(mat.get("color"))
        mat_index[mid] = len(materials)
        materials.append({
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [r, g, b, a],
                "metallicFactor": 0.0,
                "roughnessFactor": 0.6,
            },
        })
    if not materials:
        materials.append({"name": "Default", "pbrMetallicRoughness": {"baseColorFactor": [0.7, 0.65, 0.55, 1.0], "metallicFactor": 0, "roughnessFactor": 0.6}})
        mat_index["default"] = 0

    # Accumulate accessors + bufferviews + single binary buffer.
    binary = bytearray()
    buffer_views: list[dict] = []
    accessors: list[dict] = []
    meshes: list[dict] = []

    def add_accessor_from(bytes_payload, count: int, component_type: int, accessor_type: str, minv=None, maxv=None, target: int | None = None) -> int:
        offset = len(binary)
        binary.extend(bytes_payload)
        bv = {"buffer": 0, "byteOffset": offset, "byteLength": len(bytes_payload)}
        if target is not None:
            bv["target"] = target
        buffer_views.append(bv)
        accessor: dict = {
            "bufferView": len(buffer_views) - 1,
            "componentType": component_type,
            "count": count,
            "type": accessor_type,
        }
        if minv is not None:
            accessor["min"] = minv
        if maxv is not None:
            accessor["max"] = maxv
        accessors.append(accessor)
        return len(accessors) - 1

    def add_mesh(l: float, h: float, w: float, material_index: int) -> int:
        verts, norms, idx = _box_vertices_normals(l, h, w)
        lo, hi = _bounds(verts)
        pos_acc = add_accessor_from(_pack_floats(verts), len(verts), 5126, "VEC3", lo, hi, target=34962)
        nrm_acc = add_accessor_from(_pack_floats(norms), len(norms), 5126, "VEC3", target=34962)
        idx_acc = add_accessor_from(_pack_uints(idx), len(idx), 5125, "SCALAR", [min(idx)], [max(idx)], target=34963)
        meshes.append({
            "primitives": [{
                "attributes": {"POSITION": pos_acc, "NORMAL": nrm_acc},
                "indices": idx_acc,
                "material": material_index,
                "mode": 4,   # TRIANGLES
            }]
        })
        return len(meshes) - 1

    nodes: list[dict] = []

    # Room floor slab.
    room_dims = (graph.get("room") or {}).get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)
    floor_mat_idx = 0
    floor_mesh = add_mesh(room_l, 0.02, room_w, floor_mat_idx)
    nodes.append({"name": "Floor", "mesh": floor_mesh, "translation": [room_l / 2, 0.0, room_w / 2]})

    # Objects.
    for obj in graph.get("objects", []):
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        l = max(_m(d.get("length")) or 0.4, 0.05)
        w = max(_m(d.get("width")) or 0.4, 0.05)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        mat_ref = obj.get("material")
        mat_idx = mat_index.get(mat_ref, 0) if mat_ref else 0
        mesh_idx = add_mesh(l, h, w, mat_idx)
        nodes.append({
            "name": obj.get("id") or (obj.get("type") or "object"),
            "mesh": mesh_idx,
            "translation": [float(pos.get("x", 0)), float(pos.get("y", 0) or 0), float(pos.get("z", 0))],
        })

    data_uri = "data:application/octet-stream;base64," + base64.b64encode(bytes(binary)).decode("ascii")

    gltf = {
        "asset": {"version": "2.0", "generator": "KATHA AI glTF exporter"},
        "scene": 0,
        "scenes": [{"name": project_name, "nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "bufferViews": buffer_views,
        "accessors": accessors,
        "buffers": [{"byteLength": len(binary), "uri": data_uri}],
    }

    payload = json.dumps(gltf).encode("utf-8")
    return {
        "content_type": "model/gltf+json",
        "filename": f"{_safe_name(project_name)}-scene.gltf",
        "bytes": payload,
    }


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
