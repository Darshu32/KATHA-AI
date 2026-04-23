"""Wavefront OBJ exporter — 3D scene with accompanying MTL materials.

No external deps — OBJ is a plain-text vertex/face format. Each design
object becomes a named group mesh (one AABB box), each material is a
distinct MTL entry. Opens in Blender, SketchUp, Rhino, 3DS Max, Cinema 4D.
"""

from __future__ import annotations

import io
import zipfile


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _hex_to_rgb01(value: str) -> tuple[float, float, float]:
    if not isinstance(value, str):
        return (0.7, 0.65, 0.55)
    v = value.lstrip("#")
    if len(v) != 6:
        return (0.7, 0.65, 0.55)
    try:
        return int(v[0:2], 16) / 255.0, int(v[2:4], 16) / 255.0, int(v[4:6], 16) / 255.0
    except ValueError:
        return (0.7, 0.65, 0.55)


def _cube_vertices(cx: float, cy: float, cz: float, l: float, h: float, w: float) -> list[tuple[float, float, float]]:
    """World AABB. OBJ is Y-up by default, so we keep y = height."""
    hx, hy, hz = l / 2, h, w / 2  # object y starts at 0 (floor) and goes up by h
    return [
        (cx - hx, cy,      cz - hz),  # 0 bottom NW
        (cx + hx, cy,      cz - hz),  # 1 bottom NE
        (cx + hx, cy,      cz + hz),  # 2 bottom SE
        (cx - hx, cy,      cz + hz),  # 3 bottom SW
        (cx - hx, cy + hy, cz - hz),  # 4 top NW
        (cx + hx, cy + hy, cz - hz),  # 5 top NE
        (cx + hx, cy + hy, cz + hz),  # 6 top SE
        (cx - hx, cy + hy, cz + hz),  # 7 top SW
    ]


# 12 tris covering 6 faces; OBJ faces are 1-indexed.
_CUBE_FACES = [
    (1, 2, 3), (1, 3, 4),     # bottom
    (5, 7, 6), (5, 8, 7),     # top
    (1, 4, 8), (1, 8, 5),     # west
    (2, 6, 7), (2, 7, 3),     # east
    (1, 5, 6), (1, 6, 2),     # north
    (4, 3, 7), (4, 7, 8),     # south
]


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta", {})
    project = _safe_name(meta.get("project_name", "project"))

    # Build material index: material id -> name, colour.
    mat_index: dict[str, dict] = {}
    for mat in graph.get("materials", []):
        mid = (mat.get("id") or mat.get("name") or "mat").replace(" ", "_")
        mat_index[mid] = {
            "name": mat.get("name") or mid,
            "color": mat.get("color") or "#b79a74",
        }
    if not mat_index:
        mat_index["default"] = {"name": "Default", "color": "#b79a74"}

    mtl_lines: list[str] = ["# KATHA OBJ material library", f"# project: {meta.get('project_name','')}"]
    for mid, info in mat_index.items():
        r, g, b = _hex_to_rgb01(info["color"])
        mtl_lines += [
            f"newmtl {mid}",
            f"Ka {r*0.3:.4f} {g*0.3:.4f} {b*0.3:.4f}",
            f"Kd {r:.4f} {g:.4f} {b:.4f}",
            "Ks 0.25 0.25 0.25",
            "Ns 20.0",
            "illum 2",
            "",
        ]
    mtl_text = "\n".join(mtl_lines)

    obj_lines: list[str] = [
        "# KATHA AI — Wavefront OBJ export",
        f"# project: {meta.get('project_name','')}",
        f"# theme: {meta.get('theme','')}",
        f"mtllib {project}.mtl",
    ]

    # Emit room floor + ceiling as one group.
    room_dims = (graph.get("room") or {}).get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)
    room_h = float(room_dims.get("height") or 3.0)

    vertex_offset = 0
    obj_lines.append("o Room")
    obj_lines.append("g Room")
    for v in _cube_vertices(room_l / 2, 0.0, room_w / 2, room_l, 0.02, room_w):  # flat floor slab
        obj_lines.append(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
    obj_lines.append("usemtl " + next(iter(mat_index)))
    for f in _CUBE_FACES:
        obj_lines.append(f"f {f[0] + vertex_offset} {f[1] + vertex_offset} {f[2] + vertex_offset}")
    vertex_offset += 8

    # Each object = its own group.
    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "object").lower()
        oid = obj.get("id") or otype
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        cx = float(pos.get("x", 0))
        cy = float(pos.get("y", 0) or 0)
        cz = float(pos.get("z", 0))
        l = max(_m(d.get("length")) or 0.4, 0.05)
        w = max(_m(d.get("width")) or 0.4, 0.05)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        mat_ref = obj.get("material") or next(iter(mat_index))
        if mat_ref not in mat_index:
            mat_ref = next(iter(mat_index))

        obj_lines.append(f"o {oid}")
        obj_lines.append(f"g {oid}")
        obj_lines.append(f"usemtl {mat_ref}")
        for v in _cube_vertices(cx, cy, cz, l, h, w):
            obj_lines.append(f"v {v[0]:.4f} {v[1]:.4f} {v[2]:.4f}")
        for f in _CUBE_FACES:
            obj_lines.append(f"f {f[0] + vertex_offset} {f[1] + vertex_offset} {f[2] + vertex_offset}")
        vertex_offset += 8

    obj_text = "\n".join(obj_lines) + "\n"

    # Zip obj + mtl so a single download gives both.
    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{project}.obj", obj_text)
        zf.writestr(f"{project}.mtl", mtl_text)
    return {
        "content_type": "application/zip",
        "filename": f"{project}-mesh.obj.zip",
        "bytes": bio.getvalue(),
    }


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
