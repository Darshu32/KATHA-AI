"""Shared plan geometry for the diagrams — ONE source of truth so every diagram
frames the whole floor plan the same way.

Multi-room graphs place each space at a global ``origin`` on a shared plan and
give objects global coordinates spanning every room. A diagram that frames only
``spaces[0]`` (the old bug) drew the other rooms' furniture outside the box or
crammed it into one room. These helpers compute the footprint over *all* spaces
AND objects, so a diagram scaled to ``plan_bounds`` always contains everything —
for a single-room graph it degrades to that one room, and for a legacy ``room``
graph it wraps the lone room.

Convention (matches the graph): space dimensions are metres; object dimensions
may be metres or millimetres (``_m`` coerces); positions are metres, object
position is the object's centre.
"""
from __future__ import annotations


def _m(value) -> float:
    """Coerce a dimension to metres — graphs carry either m or mm."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def space_footprints(graph: dict) -> list[dict]:
    """Every space as {x, z, l, w, h, name, room_type} in world metres."""
    spaces = graph.get("spaces") or ([graph["room"]] if graph.get("room") else [])
    out: list[dict] = []
    for s in spaces:
        d = s.get("dimensions") or {}
        o = s.get("origin") or s.get("position") or {}
        out.append({
            "x": float(o.get("x", 0) or 0),
            "z": float(o.get("z", 0) or 0),
            "l": float(d.get("length") or 0.0),
            "w": float(d.get("width") or 0.0),
            "h": float(d.get("height") or 0.0),
            "name": s.get("name") or "",
            "room_type": s.get("room_type") or "",
        })
    return out


def object_footprints(graph: dict) -> list[dict]:
    """Every object as a corner-origin box in world metres.

    Keys: x, z (corner), l, w, h (size), y (base height), cx, cz (centre),
    name, type — the union of what the diagrams need.
    """
    out: list[dict] = []
    for obj in graph.get("objects", []) or []:
        d = obj.get("dimensions") or {}
        p = obj.get("position") or {}
        l = max(_m(d.get("length")) or 0.4, 0.1)
        w = max(_m(d.get("width")) or 0.4, 0.1)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        cx = float(p.get("x", 0) or 0)
        cz = float(p.get("z", 0) or 0)
        y = float(p.get("y", 0) or 0)
        out.append({
            "x": cx - l / 2, "z": cz - w / 2,
            "l": l, "w": w, "h": h, "y": y, "cx": cx, "cz": cz,
            "name": obj.get("name") or obj.get("type") or "",
            "type": obj.get("type") or "",
        })
    return out


def plan_envelope(graph: dict) -> dict:
    """The building envelope over the SPACES only (rooms), ignoring furniture.

    This is what the working drawings (plan/elevation/section/isometric) frame:
    the room shell. Furniture may sit a few cm inside or poke slightly past a
    wall, so fidelity checks compare drawn dimensions against THIS, not the
    object-inclusive footprint. Falls back to plan_bounds when there are no
    spaces. Returns {l, w, h}.
    """
    spaces = space_footprints(graph)
    if not spaces:
        pb = plan_bounds(graph)
        return {"l": pb["l"], "w": pb["w"], "h": pb["h"]}
    min_x = min(s["x"] for s in spaces)
    max_x = max(s["x"] + s["l"] for s in spaces)
    min_z = min(s["z"] for s in spaces)
    max_z = max(s["z"] + s["w"] for s in spaces)
    return {
        "l": max(max_x - min_x, 0.1),
        "w": max(max_z - min_z, 0.1),
        "h": max((s["h"] for s in spaces), default=0.1) or 0.1,
    }


def plan_bounds(graph: dict) -> dict:
    """Whole-plan footprint over every space AND object.

    Returns {min_x, min_z, l, w, h, spaces, objects, room_volume}. ``l``/``w``
    are the footprint extents (metres); ``min_x``/``min_z`` the world origin to
    subtract when projecting so a plan that doesn't start at (0,0) still frames.
    ``room_volume`` is the summed volume of the spaces (falls back to the
    footprint box when the graph has no spaces, e.g. exterior massing).
    """
    spaces = space_footprints(graph)
    objects = object_footprints(graph)

    xs0 = [s["x"] for s in spaces] + [o["x"] for o in objects]
    xs1 = [s["x"] + s["l"] for s in spaces] + [o["x"] + o["l"] for o in objects]
    zs0 = [s["z"] for s in spaces] + [o["z"] for o in objects]
    zs1 = [s["z"] + s["w"] for s in spaces] + [o["z"] + o["w"] for o in objects]
    hs = [s["h"] for s in spaces] + [o["y"] + o["h"] for o in objects]

    if not xs0:
        return {"min_x": 0.0, "min_z": 0.0, "l": 6.0, "w": 5.0, "h": 3.0,
                "spaces": spaces, "objects": objects, "room_volume": 0.0}

    min_x, max_x = min(xs0), max(xs1)
    min_z, max_z = min(zs0), max(zs1)
    foot_l = max(max_x - min_x, 0.1)
    foot_w = max(max_z - min_z, 0.1)
    foot_h = max(max(hs), 0.1)
    room_volume = (
        sum(s["l"] * s["w"] * s["h"] for s in spaces)
        or (foot_l * foot_w * foot_h)
    )
    return {
        "min_x": min_x, "min_z": min_z,
        "l": foot_l, "w": foot_w, "h": foot_h,
        "spaces": spaces, "objects": objects,
        "room_volume": room_volume,
    }
