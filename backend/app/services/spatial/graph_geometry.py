"""Pure geometry maths for the design graph — no SVG, no strings, no I/O.

This is the shared spatial core the working-drawing renderers (plan, section,
elevation, isometric, detail) project from. Everything here returns plain data
(``Rect`` tuples, dicts, lists). P1 keeps this module verbatim and swaps the SVG
layers on top of it; the SVG code around the callers is what P1 deletes.

Coordinate conventions — confirmed against the geometry kernel
(``app/services/spatial/kernel.py``), which is the authority that turns the
graph into the 3D solids everything else is derived from:

  Rooms (``graph["spaces"][i]``) — CORNER origin.
      position.x        -> left edge on the X axis
      position.z        -> near edge on the Z axis
      dimensions.length -> extent along X
      dimensions.width  -> extent along Z
      dimensions.height -> extent along Y (up); floor sits at y = 0

  Objects (``graph["objects"][i]``) — CENTRE origin, SAME axis mapping as rooms.
      position.{x,z}    -> centre on X / Z
      dimensions.length -> extent along X    (see NOTE 1)
      dimensions.width  -> extent along Z
      dimensions.height -> extent along Y (up); floor sits at y = 0
      rotation.y        -> degrees about the vertical axis (see NOTE 2)

NOTE 1 — object *length* maps to X and *width* to Z, exactly like rooms; the two
conventions are NOT transposed. Verified against ``kernel._box(l, h, w, ...)``
at kernel.py:302, which builds every object solid as ``_box(length, height,
width)`` — the identical call shape to the room floor slab at kernel.py:246. (An
early spec draft assumed objects were transposed relative to rooms; the kernel
says they are not. Using the transposed mapping would render all furniture
rotated 90°.) If that call shape ever changes, this is the one place to flip it.

NOTE 2 — ``rotation.y`` is a real field (``spatial_spec.SpatialObject.rotation_y``,
degrees about the vertical axis) and the kernel applies it. But nothing today
converts the LLM's natural-language ``orientation`` hint into a numeric angle,
so authored designs are axis-aligned in practice. ``object_rect`` returns the
axis-aligned footprint of the *unrotated* box (matching the kernel's base cube
and the existing plan renderer) and ``object_rotation_y`` exposes the angle
separately. A non-zero rotation widens the true footprint, which these rects do
not yet reflect — a known limitation, not a silent bug.
"""
from __future__ import annotations

from collections import namedtuple
from typing import Iterable

# Axis-aligned box in world metres. Invariants: x0<=x1, z0<=z1, y0<=y1.
# y is up; a floor-standing element has y0 == 0.
Rect = namedtuple("Rect", "x0 x1 z0 z1 y0 y1")

# Object types that are not free-standing furniture: structural elements and
# openings. These are excluded from the "furnishable" set the plan/section/
# isometric views place inside rooms. (Openings are drawn by their own logic.)
FURNITURE_SKIP_TYPES = frozenset(
    {"door", "window", "opening", "doorway", "wall", "floor", "slab", "building"}
)


def _f(value, default: float = 0.0) -> float:
    """Best-effort float — the graph occasionally carries strings or ``None``."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return default
    return f


def _m(value) -> float:
    """Read a graph length as metres.

    The stored graph is metres once ``normalize_graph`` has run; this mirrors the
    legacy read-time guard in the plan renderer so a stray millimetre value
    (``> 40``) is scaled down rather than blowing up the drawing. Kept identical
    to the pre-existing renderer so repointing it does not change any output.
    """
    f = _f(value)
    return f / 1000.0 if abs(f) > 40 else f


# ── Rooms ────────────────────────────────────────────────────────────────────

def room_rect(space: dict) -> Rect:
    """World-metre box for a room. Corner origin: position is the near corner."""
    d = space.get("dimensions") or {}
    p = space.get("position") or {}
    x0 = _m(p.get("x")) if p.get("x") is not None else 0.0
    z0 = _m(p.get("z")) if p.get("z") is not None else 0.0
    length = _m(d.get("length"))   # extent along X
    width = _m(d.get("width"))     # extent along Z
    height = _m(d.get("height"))   # extent along Y
    return Rect(x0, x0 + length, z0, z0 + width, 0.0, height)


def room_id(space: dict, index: int = 0) -> str:
    """Stable identifier for a room, matching the plan renderer's keying."""
    return str(space.get("id") or space.get("name") or f"room_{index + 1}")


def room_name(space: dict, index: int = 0) -> str:
    """Human label for a room (underscores flattened), matching the plan."""
    raw = space.get("name") or space.get("room_type") or space.get("type") or f"Room {index + 1}"
    return str(raw).replace("_", " ")


def placed_spaces(graph: dict) -> list[dict]:
    """Rooms that carry a usable position and non-degenerate dimensions.

    A space qualifies when it has a dict ``position`` with non-null x and z, a
    dict ``dimensions``, and positive length and width. This is the same rule
    the plan renderer used to inline; callers that want a single-room fallback
    shell should handle the empty case themselves.
    """
    out: list[dict] = []
    for s in graph.get("spaces") or []:
        if not isinstance(s, dict) or not isinstance(s.get("dimensions"), dict):
            continue
        p = s.get("position")
        if not isinstance(p, dict) or p.get("x") is None or p.get("z") is None:
            continue
        r = room_rect(s)
        if (r.x1 - r.x0) <= 0 or (r.z1 - r.z0) <= 0:
            continue
        out.append(s)
    return out


def layout_rooms(graph: dict) -> list[dict]:
    """Rooms a view should actually draw.

    Normally the placed rooms. For an un-solved or single-room graph whose
    space carries no position, falls back to the first dimensioned space treated
    as a room at the origin (``room_rect`` defaults a missing position to (0, 0),
    so it renders as a shell there). Guarantees a non-empty list whenever the
    graph has any dimensioned space, so no view is left with nothing to draw —
    the fallback that keeps single-room drawings working.
    """
    placed = placed_spaces(graph)
    if placed:
        return placed
    for s in graph.get("spaces") or []:
        if isinstance(s, dict) and isinstance(s.get("dimensions"), dict):
            r = room_rect(s)
            if (r.x1 - r.x0) > 0 and (r.z1 - r.z0) > 0:
                return [s]
    return []


# ── Objects ──────────────────────────────────────────────────────────────────

def object_rect(obj: dict) -> Rect:
    """World-metre footprint for an object. Centre origin; length→X, width→Z.

    Returns the axis-aligned footprint of the *unrotated* box (see module
    NOTE 2). Degenerate dimensions are floored to 0.2 m so a piece never
    collapses to a zero-area rect, matching the plan renderer.
    """
    d = obj.get("dimensions") or {}
    p = obj.get("position") or {}
    cx, cz = _m(p.get("x")), _m(p.get("z"))
    length = max(_m(d.get("length")), 0.2) or 0.5   # extent along X
    width = max(_m(d.get("width")), 0.2) or 0.5      # extent along Z
    height = max(_m(d.get("height")), 0.2) or 0.5    # extent along Y
    return Rect(cx - length / 2, cx + length / 2, cz - width / 2, cz + width / 2, 0.0, height)


def object_rotation_y(obj: dict) -> float:
    """Vertical-axis rotation in degrees, or 0. Tolerates dict or list form.

    The schema prompt shows ``"rotation": [x, y, z]`` while the kernel reads
    ``rotation.y``; accept both so a rotated piece is never misread as 0.
    """
    rot = obj.get("rotation")
    if isinstance(rot, dict):
        return _f(rot.get("y"))
    if isinstance(rot, (list, tuple)) and len(rot) >= 2:
        return _f(rot[1])
    return 0.0


def is_furnishable(obj: dict) -> bool:
    """True for free-standing furniture/fixtures (not structure or openings)."""
    return isinstance(obj, dict) and str(obj.get("type", "")).lower() not in FURNITURE_SKIP_TYPES


def furnishable_objects(graph: dict) -> list[dict]:
    """Objects the room-scale views place: everything minus structure/openings."""
    return [o for o in (graph.get("objects") or []) if is_furnishable(o)]


def depictable_objects(graph: dict) -> list[dict]:
    """Objects a view is expected to *depict* — everything except the wall shell.

    Broader than :func:`furnishable_objects`: it keeps openings (windows, doors)
    because a view must still show them, just drawn as openings rather than
    free-standing furniture. Matches the fidelity contract in
    ``view_fidelity`` (only ``role == "wall"`` is coverage-exempt), so nothing a
    user designed is silently dropped from a drawing.
    """
    out: list[dict] = []
    for o in graph.get("objects") or []:
        if not isinstance(o, dict):
            continue
        if str(o.get("role") or "").lower() == "wall" or str(o.get("type") or "").lower() == "wall":
            continue
        out.append(o)
    return out


# ── Aggregates ───────────────────────────────────────────────────────────────

def bbox_of_rects(rects: Iterable[Rect]) -> Rect | None:
    """Union bounding box over rects, or ``None`` if there are none.

    y0 is the lowest floor (0) and y1 is the tallest top, so ``building_bbox``
    reports the height of the tallest room.
    """
    rects = list(rects)
    if not rects:
        return None
    return Rect(
        min(r.x0 for r in rects), max(r.x1 for r in rects),
        min(r.z0 for r in rects), max(r.z1 for r in rects),
        min(r.y0 for r in rects), max(r.y1 for r in rects),
    )


def building_bbox(graph: dict) -> Rect | None:
    """Union box over every placed room; y1 is the tallest room. ``None`` if empty."""
    return bbox_of_rects(room_rect(s) for s in placed_spaces(graph))


def rect_contains_point(r: Rect, x: float, z: float) -> bool:
    """Half-open footprint test on the X/Z plane (y ignored).

    Half-open on the high edge so a point on a shared wall between two rooms
    lands in exactly one of them, never both.
    """
    return r.x0 <= x < r.x1 and r.z0 <= z < r.z1


def assign_objects(
    graph: dict,
    objects: list[dict] | None = None,
    rooms: list[dict] | None = None,
) -> tuple[dict[str, list[dict]], list[dict]]:
    """Assign each object to the room whose footprint contains its CENTRE.

    Containment is tested on the centre point only — not overlap — so a sofa
    pushed against a wall (its rect straddling two rooms) still resolves to the
    room it actually sits in. An object whose centre falls in no placed room is
    returned in ``orphans`` rather than dropped; every caller is expected to log
    a warning when ``orphans`` is non-empty and draw them nowhere. Silently
    swallowing furniture is how the ``spaces[0]`` collapse survived unnoticed.

    Returns ``({room_id: [objects...]}, [orphans...])``. ``room_id`` matches
    :func:`room_id` so callers can cross-reference room metadata. Rooms with no
    objects are present with an empty list.

    ``objects`` defaults to :func:`furnishable_objects` (structure/openings
    excluded); pass an explicit list to assign a different set. ``rooms``
    defaults to :func:`placed_spaces`; pass the view's :func:`layout_rooms` so a
    single-room fallback shell still receives its furniture.
    """
    room_list = placed_spaces(graph) if rooms is None else rooms
    room_rects = [(room_id(s, i), room_rect(s)) for i, s in enumerate(room_list)]
    by_room: dict[str, list[dict]] = {rid: [] for rid, _ in room_rects}
    orphans: list[dict] = []

    objs = furnishable_objects(graph) if objects is None else objects
    for o in objs:
        if not isinstance(o, dict):
            continue
        r = object_rect(o)
        cx = (r.x0 + r.x1) / 2.0
        cz = (r.z0 + r.z1) / 2.0
        for rid, rr in room_rects:
            if rect_contains_point(rr, cx, cz):
                by_room[rid].append(o)
                break
        else:
            orphans.append(o)
    return by_room, orphans
