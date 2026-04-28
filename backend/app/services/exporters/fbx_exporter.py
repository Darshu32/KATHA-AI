"""FBX (Autodesk) exporter — ASCII FBX 7.4.

ASCII FBX so the file is plain-text and dependency-free. Each design
object becomes a `Model: "Mesh::<oid>"` with embedded mesh data.

Compatible with Autodesk 3ds Max, Maya, MotionBuilder, Blender, Unreal,
Unity. ASCII FBX is the canonical interchange format alongside the
binary form; every Autodesk tool reads both.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timezone


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


def _box_vertices(cx: float, cy: float, cz: float, l: float, h: float, w: float) -> list[tuple[float, float, float]]:
    hx, hz = l / 2.0, w / 2.0
    return [
        (cx - hx, cy,     cz - hz),
        (cx + hx, cy,     cz - hz),
        (cx + hx, cy,     cz + hz),
        (cx - hx, cy,     cz + hz),
        (cx - hx, cy + h, cz - hz),
        (cx + hx, cy + h, cz - hz),
        (cx + hx, cy + h, cz + hz),
        (cx - hx, cy + h, cz + hz),
    ]


# Quads (FBX uses negative-1 to mark end of polygon when winding indices).
_BOX_QUADS = [
    (0, 1, 2, 3),  # bottom
    (4, 7, 6, 5),  # top
    (0, 4, 5, 1),  # north
    (1, 5, 6, 2),  # east
    (2, 6, 7, 3),  # south
    (3, 7, 4, 0),  # west
]


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "project")).strip("-") or "project"


def _emit_mesh(model_id: int, geom_id: int, name: str,
               verts: list[tuple[float, float, float]]) -> list[str]:
    flat = ",".join(f"{c:.6f}" for v in verts for c in v)
    indices: list[int] = []
    for q in _BOX_QUADS:
        a, b, c, d = q
        indices.extend([a, b, c, ~d])  # ~d == -d-1 (FBX end-of-poly marker)
    poly_idx = ",".join(str(i) for i in indices)

    return [
        f'\tGeometry: {geom_id}, "Geometry::{name}", "Mesh" {{',
        f'\t\tVertices: *{len(verts)*3} {{',
        f"\t\t\ta: {flat}",
        '\t\t}',
        f'\t\tPolygonVertexIndex: *{len(indices)} {{',
        f"\t\t\ta: {poly_idx}",
        '\t\t}',
        '\t\tGeometryVersion: 124',
        '\t\tLayerElementNormal: 0 {',
        '\t\t\tVersion: 102',
        '\t\t\tName: ""',
        '\t\t\tMappingInformationType: "ByPolygonVertex"',
        '\t\t\tReferenceInformationType: "Direct"',
        '\t\t\tNormals: *0 { a: }',
        '\t\t}',
        '\t\tLayer: 0 {',
        '\t\t\tVersion: 100',
        '\t\t\tLayerElement: { Type: "LayerElementNormal" TypedIndex: 0 }',
        '\t\t}',
        '\t}',
        f'\tModel: {model_id}, "Model::{name}", "Mesh" {{',
        '\t\tVersion: 232',
        '\t\tShadingModel: "lambert"',
        '\t}',
    ]


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta", {})
    project = _safe_name(meta.get("project_name", "project"))
    today = datetime.now(timezone.utc)

    # Header.
    head = [
        '; FBX 7.4.0 project file',
        '; KATHA AI export',
        f'; project: {meta.get("project_name", "")}',
        '',
        'FBXHeaderExtension: {',
        '\tFBXHeaderVersion: 1003',
        '\tFBXVersion: 7400',
        '\tCreationTimeStamp: {',
        f'\t\tVersion: 1000',
        f'\t\tYear: {today.year}',
        f'\t\tMonth: {today.month}',
        f'\t\tDay: {today.day}',
        f'\t\tHour: {today.hour}',
        f'\t\tMinute: {today.minute}',
        f'\t\tSecond: {today.second}',
        '\t\tMillisecond: 0',
        '\t}',
        '\tCreator: "KATHA AI exporter (ascii fbx 7.4)"',
        '}',
        f'CreationTime: "{today.isoformat()}"',
        f'Creator: "KATHA AI ({project})"',
        '',
        'GlobalSettings: {',
        '\tVersion: 1000',
        '\tProperties70: {',
        '\t\tP: "UpAxis", "int", "Integer", "",1',
        '\t\tP: "FrontAxis", "int", "Integer", "",2',
        '\t\tP: "CoordAxis", "int", "Integer", "",0',
        '\t\tP: "OriginalUpAxis", "int", "Integer", "",1',
        '\t\tP: "UnitScaleFactor", "double", "Number", "",100',
        '\t\tP: "TimeMode", "enum", "", "",6',
        '\t\tP: "TimeSpanStart", "KTime", "Time", "",0',
        '\t\tP: "TimeSpanStop", "KTime", "Time", "",46186158000',
        '\t}',
        '}',
        '',
    ]

    # Material catalogue.
    materials: dict[str, tuple[float, float, float]] = {}
    for mat in graph.get("materials") or []:
        mid = (mat.get("id") or mat.get("name") or "mat").replace(" ", "_")
        materials[mid] = _hex_to_rgb01(mat.get("color") or "#b79a74")
    if not materials:
        materials["default"] = (0.7, 0.65, 0.55)

    # Objects from the graph.
    room_dims = (graph.get("room") or {}).get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)

    objects_block = ['Objects: {']
    next_id = 1000
    pieces: list[tuple[int, int, str]] = []   # (model_id, geom_id, name)

    # Floor slab.
    floor_verts = _box_vertices(room_l / 2.0, 0.0, room_w / 2.0, room_l, 0.02, room_w)
    objects_block += _emit_mesh(next_id, next_id + 1, "Room_Floor", floor_verts)
    pieces.append((next_id, next_id + 1, "Room_Floor"))
    next_id += 2

    for obj in graph.get("objects") or []:
        otype = (obj.get("type") or "object").lower()
        oid = _safe_name(obj.get("id") or otype)
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        cx = float(pos.get("x", 0))
        cy = float(pos.get("y", 0) or 0)
        cz = float(pos.get("z", 0))
        l = max(_m(d.get("length")) or 0.4, 0.05)
        w = max(_m(d.get("width")) or 0.4, 0.05)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        verts = _box_vertices(cx, cy, cz, l, h, w)
        objects_block += _emit_mesh(next_id, next_id + 1, oid, verts)
        pieces.append((next_id, next_id + 1, oid))
        next_id += 2

    # Materials.
    mat_ids: dict[str, int] = {}
    for mid, (r, g, b) in materials.items():
        mat_ids[mid] = next_id
        objects_block += [
            f'\tMaterial: {next_id}, "Material::{mid}", "" {{',
            '\t\tVersion: 102',
            '\t\tShadingModel: "lambert"',
            '\t\tProperties70: {',
            f'\t\t\tP: "DiffuseColor", "Color", "", "A",{r:.4f},{g:.4f},{b:.4f}',
            '\t\t\tP: "DiffuseFactor", "Number", "", "A",1.0',
            '\t\t}',
            '\t}',
        ]
        next_id += 1

    objects_block.append('}')

    # Connections — link every Geometry to its Model, plus a default material.
    connections = ['Connections: {']
    default_mat_id = next(iter(mat_ids.values()))
    for model_id, geom_id, name in pieces:
        connections.append(f'\tC: "OO",{geom_id},{model_id}')
        connections.append(f'\tC: "OO",{default_mat_id},{model_id}')
        connections.append(f'\tC: "OO",{model_id},0')
    connections.append('}')

    fbx_text = "\n".join(head + objects_block + [''] + connections + ['']) + "\n"

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{project}.fbx", fbx_text)
    return {
        "content_type": "application/zip",
        "filename": f"{project}-scene.fbx.zip",
        "bytes": bio.getvalue(),
    }
