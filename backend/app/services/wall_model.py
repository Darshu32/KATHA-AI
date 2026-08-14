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

from collections import defaultdict
from typing import Any

from app.config import get_settings

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


# ── Multi-room walls (shared-partition aware) — Stage C of the layout cascade ──
#
# Given several *placed* rooms, emit wall SEGMENTS such that a wall shared by two
# rooms appears ONCE — a "partition" tagged with both rooms, centered on the
# shared line — and an edge facing outside is an "exterior" segment tagged with
# its single room. A coordinate sweep (segment at every endpoint, then merge
# equal-classification neighbours) makes T-junctions and partial overlaps come
# out right. The single-room ``derive_wall_model`` above is deliberately left
# untouched; this is the parallel path the multi-room consumers (Stage D) adopt.
#
# Convention: solved room rectangles are wall CENTERLINES — a partition sits on
# the shared boundary line (``at``), so the footprint stays exact.


def _snap(v: float) -> float:
    return round(float(v), 3)


def _covering(edges: list[tuple[float, float, dict]], a: float, b: float, eps: float = 1e-6) -> dict | None:
    """The single room whose edge interval covers ``[a, b]`` (or None). Rooms in
    a tiling never overlap on one side of a line, so at most one matches."""
    for lo, hi, room in edges:
        if lo <= a + eps and hi >= b - eps:
            return room
    return None


def _merge_cells(cells: list[tuple]) -> list[list]:
    """Coalesce contiguous cells sharing a (kind, room-set) classification."""
    merged: list[list] = []
    for kind, key, a, b, rooms in cells:
        prev = merged[-1] if merged else None
        if prev and prev[0] == kind and prev[1] == key and abs(prev[3] - a) < 1e-6:
            prev[3] = b
        else:
            merged.append([kind, key, a, b, rooms])
    return merged


def _sweep_axis(rooms: list[dict], axis: str, thickness: float) -> list[dict]:
    """Emit wall segments for one orientation. ``axis='z'`` → vertical walls
    (run along z, fixed x); ``axis='x'`` → horizontal walls (run along x,
    fixed z)."""
    if axis == "z":
        line_lo, line_ext = (lambda r: r["x"]), (lambda r: r["length"])
        span_lo, span_ext = (lambda r: r["z"]), (lambda r: r["width"])
    else:
        line_lo, line_ext = (lambda r: r["z"]), (lambda r: r["width"])
        span_lo, span_ext = (lambda r: r["x"]), (lambda r: r["length"])

    # Group room edges by the line they sit on. "plus" = the room lies on the
    # +line side of this coordinate (its low edge); "minus" = the -line side.
    groups: dict[float, dict[str, list]] = defaultdict(lambda: {"plus": [], "minus": []})
    for r in rooms:
        lo, hi = _snap(line_lo(r)), _snap(line_lo(r) + line_ext(r))
        a, b = _snap(span_lo(r)), _snap(span_lo(r) + span_ext(r))
        groups[lo]["plus"].append((a, b, r))
        groups[hi]["minus"].append((a, b, r))

    segments: list[dict] = []
    for lc in sorted(groups):
        plus, minus = groups[lc]["plus"], groups[lc]["minus"]
        breakpoints = sorted({p for edge in (plus + minus) for p in (edge[0], edge[1])})
        cells: list[tuple] = []
        for a, b in zip(breakpoints, breakpoints[1:]):
            pr = _covering(plus, a, b)   # room on the +line side
            mr = _covering(minus, a, b)  # room on the -line side
            if pr and mr:
                cells.append(("partition", frozenset((pr["id"], mr["id"])), a, b, [mr, pr]))
            elif pr:
                cells.append(("exterior", frozenset((pr["id"],)), a, b, [pr]))
            elif mr:
                cells.append(("exterior", frozenset((mr["id"],)), a, b, [mr]))
            # neither → a gap in the tiling; nothing to build
        for kind, _key, a, b, rms in _merge_cells(cells):
            segments.append(
                {
                    "runs": axis,
                    "at": lc,
                    "start": a,
                    "end": b,
                    "height": round(max(rm["height"] for rm in rms), 4),
                    "thickness": thickness,
                    "kind": kind,
                    "rooms": sorted({rm["id"] for rm in rms}),
                    "openings": [],
                }
            )
    return segments


# Opening dimensions — door/window sizes, sill/head heights, and the shortest
# wall a door/window can occupy — are read from Settings (see ``app.config``),
# so they come from one documented, code-sourced, env-overridable place rather
# than magic numbers. ``_add_openings`` reads them per call (get_settings is
# cached), which keeps the generation opening-pass, the renderers and the IFC
# export all sizing openings from the same source.


def _adjacency_pairs(adjacencies) -> set[frozenset]:
    """Normalise ``[{"a","b"}]`` or ``[[a, b]]`` into a set of unordered id pairs."""
    pairs: set[frozenset] = set()
    for a in adjacencies or []:
        if isinstance(a, dict):
            x, y = a.get("a"), a.get("b")
        elif isinstance(a, (list, tuple)) and len(a) >= 2:
            x, y = a[0], a[1]
        else:
            continue
        if x and y:
            pairs.add(frozenset((str(x), str(y))))
    return pairs


def _add_openings(segments: list[dict], adjacencies) -> None:
    """Place a door in each partition between adjacent rooms (from the adjacency
    graph, one per pair) and a window on each long-enough exterior wall. In-place.
    ``center`` is measured from the segment start (0 … length). Opening sizes
    come from Settings (code-sourced), not hardcoded literals."""
    s = get_settings()
    door_w, door_h = s.opening_door_width_m, s.opening_door_height_m
    win_w = s.opening_window_width_m
    win_sill, win_head = s.opening_window_sill_m, s.opening_window_head_m
    min_door, min_window = s.opening_min_door_wall_m, s.opening_min_window_wall_m
    adj = _adjacency_pairs(adjacencies)
    doored: set[frozenset] = set()
    for seg in segments:
        length = seg["end"] - seg["start"]
        if seg["kind"] == "partition":
            pair = frozenset(seg["rooms"])
            if pair in adj and pair not in doored and length >= min_door:
                seg["openings"] = [{
                    "source_id": f"door-{'-'.join(sorted(seg['rooms']))}",
                    "kind": "door",
                    "center": round(length / 2, 4),
                    "width": round(min(door_w, length * 0.6), 4),
                    "sill": 0.0,
                    "head": round(min(door_h, seg["height"]), 4),
                }]
                doored.add(pair)
        elif length >= min_window:  # exterior wall
            head = min(win_head, seg["height"])
            sill = min(win_sill, max(head - 0.6, 0.0))
            seg["openings"] = [{
                "source_id": f"win-{seg['id']}",
                "kind": "window",
                "center": round(length / 2, 4),
                "width": round(min(win_w, length * 0.6), 4),
                "sill": round(sill, 4),
                "head": round(head, 4),
            }]


def derive_multiroom_wall_model(
    rooms: list[dict],
    adjacencies: list | None = None,
    thickness: float = WALL_THICKNESS_M,
    default_height: float = 2.7,
) -> list[dict]:
    """Shared-partition-aware walls for a placed multi-room plan, with openings.

    Each input room is ``{id, x, z, length, width, height?}`` (metres; ``x``/``z``
    the min corner, ``length`` spanning x, ``width`` spanning z). Returns a flat
    list of wall segments::

        {id, runs: "x"|"z", at, start, end, height, thickness,
         kind: "exterior"|"partition", rooms: [one or two ids],
         openings: [{source_id, kind, center, width, sill, head}, ...]}

    A single room yields its four exterior walls (no partitions). ``adjacencies``
    (pairs of room ids) drives door placement — a door goes in the partition
    between each connected pair; windows go on long-enough exterior walls. Pass
    no adjacencies for walls-only (windows still placed).
    """
    norm: list[dict] = []
    for r in rooms:
        if not isinstance(r, dict):
            continue
        length, width = _num(r.get("length")), _num(r.get("width"))
        if length <= 0 or width <= 0:
            continue
        norm.append(
            {
                "id": str(r.get("id") or f"room_{len(norm) + 1}"),
                "x": _num(r.get("x")),
                "z": _num(r.get("z")),
                "length": length,
                "width": width,
                "height": _num(r.get("height")) or default_height,
            }
        )

    segments = _sweep_axis(norm, "z", thickness) + _sweep_axis(norm, "x", thickness)
    for i, seg in enumerate(segments):
        seg["id"] = f"wall_{i + 1}"
    _add_openings(segments, adjacencies)
    return segments
