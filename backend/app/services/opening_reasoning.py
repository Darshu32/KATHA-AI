"""Deterministic openings — promote the wall model's derived windows and doors
into real graph objects.

Openings only reach the design graph today when the LLM happens to emit them
(usually because the prompt named them). Multi-room plans get none, so every
2D/3D view had to *synthesise* windows at render time from hardcoded sizes — the
band-aid this pass removes. Here we derive openings once, from the placed
geometry (adjacency doors + exterior windows via ``derive_multiroom_wall_model``,
the same source the section and IFC export already trust), and write them into
``graph["objects"]`` as ordinary window/door objects. Every consumer (plan,
elevation, section, isometric, 3D, IFC) then reads one source of truth.

Idempotent: a design that already carries opening objects (the LLM authored
them, e.g. because the prompt named windows) is left untouched.
"""

from __future__ import annotations

from app.services.spatial.graph_geometry import layout_rooms, room_id, room_rect
from app.services.wall_model import WALL_THICKNESS_M, derive_multiroom_wall_model

_OPENING_ROLES = {"window", "door"}
# Mirror the LLM-authored opening objects so a derived opening is styled and
# treated identically downstream (themes, exporters, click-to-edit).
_WINDOW_STYLE = {"color": "#e8e4db", "material": "glass"}
_DOOR_STYLE = {"color": "#3b3b3b", "material": "matte metal"}


def _has_openings(graph: dict) -> bool:
    return any(
        str(o.get("role") or "").lower() in _OPENING_ROLES
        for o in (graph.get("objects") or [])
        if isinstance(o, dict)
    )


def _opening_object(
    idx: int, kind: str, wall_kind: str, x: float, y: float, z: float,
    along_x: bool, size: float, height: float, thickness: float,
) -> dict:
    # object_rect maps length -> X-extent, width -> Z-extent. A wall-parallel
    # opening spans its wall by ``size`` and is thin (wall thickness) across it,
    # so which of length/width carries ``size`` depends on the wall's run axis.
    length, width = (size, thickness) if along_x else (thickness, size)
    return {
        "id": f"{kind}_{idx}",
        "name": kind,
        "role": kind,
        "type": kind,
        **(_WINDOW_STYLE if kind == "window" else _DOOR_STYLE),
        "position": {"x": round(x, 3), "y": round(y, 3), "z": round(z, 3)},
        "rotation": {"x": 0.0, "y": 0.0, "z": 0.0},
        "dimensions": {
            "unit": "m",
            "length": round(length, 3),
            "width": round(width, 3),
            "height": round(height, 3),
        },
        # Provenance so a renderer can tell a derived opening from an authored
        # one, and which wall it sits on (an exterior elevation shows exterior
        # openings, not interior partition doors).
        "source": "derived",
        "wall": wall_kind,
    }


def derive_openings(graph: dict) -> dict:
    """Enrich ``graph`` in place with geometry-derived window/door objects.

    Returns the same graph. No-op when the graph already carries opening objects
    or has no placed rooms — so it only fills the gap, never overrides a design.
    """
    if not isinstance(graph, dict) or _has_openings(graph):
        return graph
    rooms = layout_rooms(graph)
    if not rooms:
        return graph

    wm_rooms: list[dict] = []
    for i, s in enumerate(rooms):
        r = room_rect(s)
        if (r.x1 - r.x0) <= 0 or (r.z1 - r.z0) <= 0:
            continue
        wm_rooms.append({
            "id": room_id(s, i), "x": r.x0, "z": r.z0,
            "length": r.x1 - r.x0, "width": r.z1 - r.z0, "height": r.y1,
        })
    if not wm_rooms:
        return graph

    new_objs: list[dict] = []
    counts = {"window": 0, "door": 0}
    for seg in derive_multiroom_wall_model(wm_rooms, graph.get("adjacencies")):
        along_x = seg.get("runs") == "x"
        at = float(seg.get("at", 0.0))
        start = float(seg.get("start", 0.0))
        thickness = float(seg.get("thickness", WALL_THICKNESS_M))
        wall_kind = str(seg.get("kind") or "exterior")
        for op in seg.get("openings", []):
            kind = "door" if str(op.get("kind") or "").lower() == "door" else "window"
            size = float(op.get("width", 0.0))
            sill = float(op.get("sill", 0.0))
            head = float(op.get("head", 0.0))
            if size <= 0 or head <= sill:
                continue
            u = start + float(op.get("center", 0.0))          # coord along the wall
            x, z = (u, at) if along_x else (at, u)             # world position
            counts[kind] += 1
            new_objs.append(_opening_object(
                counts[kind], kind, wall_kind, x, sill, z,
                along_x, size, head - sill, thickness,
            ))

    if new_objs:
        graph.setdefault("objects", []).extend(new_objs)
    return graph
