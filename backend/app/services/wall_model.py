"""Deterministic perimeter-wall + opening model derived from the design graph.

Today the graph carries the room as bare envelope dimensions and treats every
window/door as an independent box floating on a wall line. That is why a
section reads flat (a window is a box in front of a box) and why the IFC export
ships walls and windows as unrelated solids instead of an opening *voiding* a
wall.

This module derives — deterministically, no LLM — the thing both consumers
actually need: **four perimeter walls, each with real openings punched into
it.** One source of truth, read by:

    * the SVG renderers (``architectural_views_service``) → windows/doors drawn
      as genuine holes in the wall, and
    * the IFC exporter → ``IfcWall`` with ``IfcOpeningElement`` voids +
      ``IfcWindow`` / ``IfcDoor`` filling them.

It reads the **normalized** graph (metric, depth on z, edge elements already
snapped to a wall by ``graph_normalizer``), so wall assignment is a cheap
"which edge is this opening on?" check.

Coordinate model (post-normalization, metres):
    room length ``L`` spans x, width ``W`` spans z (floor plane), height ``H`` = y.
    Walls: south @ z=0 and north @ z=W run along x; west @ x=0 and east @ x=L
    run along z.
"""

from __future__ import annotations

from typing import Any

# Default wall thickness (metres) when the graph doesn't specify one. A neutral
# interior value; exterior walls in practice run thicker, but a single constant
# keeps the derivation deterministic and is easily overridden later per-region.
WALL_THICKNESS_M = 0.15

# Where a window sits vertically when the graph gives no sill height.
_DEFAULT_WINDOW_SILL_M = 0.9

_OPENING_ROLES = {"window", "door"}
_MIN_ROOM = 0.5


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out and out not in (float("inf"), float("-inf")) else default


def _primary_space(graph: dict) -> dict:
    spaces = graph.get("spaces") if isinstance(graph, dict) else None
    if isinstance(spaces, list) and spaces and isinstance(spaces[0], dict):
        return spaces[0]
    room = graph.get("room") if isinstance(graph, dict) else None
    return room if isinstance(room, dict) else {}


def _room(graph: dict) -> tuple[float, float, float]:
    dims = (_primary_space(graph).get("dimensions") or {}) if graph else {}
    L = max(_num(dims.get("length"), 6.0), _MIN_ROOM)
    W = max(_num(dims.get("width"), 4.0), _MIN_ROOM)
    H = max(_num(dims.get("height"), 2.7), _MIN_ROOM)
    return L, W, H


def _objects(graph: dict) -> list[dict]:
    objs = graph.get("objects") if isinstance(graph, dict) else None
    return [o for o in objs if isinstance(o, dict)] if isinstance(objs, list) else []


def _opening_role(obj: dict) -> str | None:
    role = str(obj.get("role") or "").lower()
    if role in _OPENING_ROLES:
        return role
    # Fallback for un-normalized graphs: sniff the type string.
    t = str(obj.get("type") or "").lower()
    if any(k in t for k in ("window", "glazing", "skylight")):
        return "window"
    if any(k in t for k in ("door", "doorway", "entry")):
        return "door"
    return None


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if hi < lo else max(lo, min(hi, v))


def _new_wall(wall_id: str, side: str, runs: str, at: float, length: float, height: float, thickness: float) -> dict:
    return {
        "id": wall_id,
        "side": side,
        "runs": runs,            # axis the wall length runs along ("x" or "z")
        "at": round(at, 4),      # fixed coordinate (z for south/north, x for west/east)
        "length": round(length, 4),
        "height": round(height, 4),
        "thickness": thickness,
        "openings": [],          # filled below
    }


def derive_wall_model(graph: dict, thickness: float = WALL_THICKNESS_M) -> dict:
    """Return the four perimeter walls with their openings.

    Structure::

        {
          "room": {"length": L, "width": W, "height": H},
          "thickness": t,
          "walls": [ {id, side, runs, at, length, height, thickness, openings:[...]} , ... ],
        }

    Each opening::

        {"source_id", "kind": "window"|"door", "center", "width",
         "sill", "head", "height"}

    ``center`` is the opening's midpoint measured along the wall from its start
    (x for south/north walls, z for west/east); ``width`` is its extent *along*
    the wall (the larger horizontal dimension, so a mis-oriented thin window is
    corrected here).
    """
    L, W, H = _room(graph)
    walls = {
        "south": _new_wall("wall_south", "south", "x", 0.0, L, H, thickness),
        "north": _new_wall("wall_north", "north", "x", W, L, H, thickness),
        "west": _new_wall("wall_west", "west", "z", 0.0, W, H, thickness),
        "east": _new_wall("wall_east", "east", "z", L, W, H, thickness),
    }

    for obj in _objects(graph):
        kind = _opening_role(obj)
        if kind is None:
            continue
        pos = obj.get("position") or {}
        dim = obj.get("dimensions") or {}
        px, pz, py = _num(pos.get("x")), _num(pos.get("z")), _num(pos.get("y"))
        dx = max(_num(dim.get("width"), 0.5), 0.05)
        dz = max(_num(dim.get("length"), 0.5), 0.05)
        dy = max(_num(dim.get("height"), 1.2), 0.05)

        # The opening's extent *along the wall* is the larger horizontal
        # dimension; the smaller one is its depth into the wall. This corrects
        # openings authored perpendicular to the wall they were snapped to
        # (e.g. a 1.5 m window stored as width=0.1, length=1.5).
        along = max(dx, dz)

        # Which wall? Nearest edge (openings are already snapped there).
        dist = {"west": px, "east": L - px, "south": pz, "north": W - pz}
        side = min(dist, key=lambda s: abs(dist[s]))
        wall = walls[side]
        wall_len = wall["length"]

        width = min(along, wall_len)
        center = _clamp(px if side in ("south", "north") else pz, width / 2, wall_len - width / 2)

        if kind == "door":
            sill = 0.0
        else:
            sill = py if py > 0.05 else _DEFAULT_WINDOW_SILL_M
        sill = _clamp(sill, 0.0, max(H - 0.1, 0.0))
        head = min(sill + dy, H)

        wall["openings"].append(
            {
                "source_id": obj.get("id") or f"{kind}",
                "kind": kind,
                "center": round(center, 4),
                "width": round(width, 4),
                "sill": round(sill, 4),
                "head": round(head, 4),
                "height": round(head - sill, 4),
            }
        )

    for wall in walls.values():
        wall["openings"].sort(key=lambda o: o["center"])

    return {
        "room": {"length": round(L, 4), "width": round(W, 4), "height": round(H, 4)},
        "thickness": thickness,
        "walls": [walls["south"], walls["north"], walls["west"], walls["east"]],
    }


def wall_by_side(model: dict, side: str) -> dict | None:
    """Convenience lookup by side name ('south'|'north'|'west'|'east')."""
    for wall in model.get("walls", []):
        if wall.get("side") == side:
            return wall
    return None
