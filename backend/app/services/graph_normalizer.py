"""Deterministic design-graph normalization + validation.

This is the *single chokepoint* every design graph passes through before it
is persisted (see ``design_graph_service.save_graph_version``). Every drawing
renderer, the 3D pipeline, and cost estimation read the normalized graph, so
fixing a class of defect here fixes it for **all** current and future designs
rather than patching each of the ~13 downstream outputs individually.

Canonical contract (matches the editable 2D canvas — the product source of
truth, see ``frontend/components/canvas/DraggableObject2D.tsx``):

    * Units are metric. Every linear value is in **metres**.
    * Axes: ``x`` = width axis (room length), ``z`` = depth axis (room width,
      the floor plane), ``y`` = height (vertical; ~0 for floor furniture).
    * ``dimensions.width`` is the object's x-extent, ``dimensions.length`` is
      its z-extent (depth), ``dimensions.height`` is vertical.
    * Room dimensions: ``length`` spans x, ``width`` spans z.

The normalizer is **idempotent**: running it on an already-clean graph is a
no-op (modulo the report). That property is what makes it safe to run on every
save, including manual edits of graphs that were already normalized.

Defects this layer corrects (root causes A–C from the drawing audit):

    A. Axis collapse — depth authored into ``position.y`` with ``z`` pinned to
       0, so every object stacks on one centreline. Detected by axis spread
       and corrected by swapping y<->z for positions.
    B. Unit ambiguity — graphs carry no explicit unit, so renderers default to
       "ft" while values are metres. Corrected by stamping ``unit="m"``.
    C. Oversized / out-of-bounds objects — footprints larger than the room or
       positioned outside the walls. Corrected by scaling to fit and clamping
       the centre so the bounding box stays inside the room.

It also classifies every object with a ``role`` (wall / window / door /
column / lighting / decor / furniture) and snaps edge elements
(wall/window/door) to the nearest wall. ``role`` is the metadata the working
drawings need to switch out of "furniture" mode (root cause D's data half;
the prompt-side re-domaining is a separate change).
"""

from __future__ import annotations

import copy
from typing import Any

# ── Tunable constants ────────────────────────────────────────────────────────

FEET_TO_M = 0.3048

# Axis-collapse detection: the depth axis is considered "collapsed" when its
# spread is below this (metres) while another axis carries real spread.
_AXIS_FLAT_EPS = 0.25
# ...and the candidate depth axis must spread at least this much to swap in.
_AXIS_SWAP_MIN_SPAN = 1.0

# A single object footprint may not exceed this fraction of the room area.
_MAX_FOOTPRINT_FRACTION = 0.6
# An object extent may not exceed this fraction of the matching room extent.
_MAX_EXTENT_FRACTION = 0.95
# Minimum sane object extent (metres) — guards against zero/NaN dimensions.
_MIN_EXTENT = 0.1

# Edge-element snap inset from the wall (metres).
_EDGE_INSET = 0.0

# type-substring → role. First match wins; order matters (specific first).
_ROLE_RULES: list[tuple[tuple[str, ...], str]] = [
    (("window", "glazing", "skylight"), "window"),
    (("door", "doorway", "entry"), "door"),
    (("wall", "partition"), "wall"),
    (("column", "pillar", "post"), "column"),
    (("beam",), "beam"),
    (("stair", "staircase"), "stair"),
    (
        ("lamp", "light", "lighting", "sconce", "pendant", "chandelier", "spotlight"),
        "lighting",
    ),
    (
        ("plant", "art", "decor", "vase", "painting", "mirror", "rug", "curtain"),
        "decor",
    ),
]

_EDGE_ROLES = {"wall", "window", "door"}


# ── Small helpers ────────────────────────────────────────────────────────────


def _num(value: Any, default: float = 0.0) -> float:
    """Coerce to float, tolerating None / strings / NaN."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    if out != out or out in (float("inf"), float("-inf")):  # NaN / inf
        return default
    return out


def _primary_space(graph: dict[str, Any]) -> dict[str, Any]:
    spaces = graph.get("spaces")
    if isinstance(spaces, list) and spaces and isinstance(spaces[0], dict):
        return spaces[0]
    room = graph.get("room")
    if isinstance(room, dict):
        return room
    return {}


def _room_dimensions(graph: dict[str, Any]) -> dict[str, float]:
    space = _primary_space(graph)
    dims = space.get("dimensions") if isinstance(space, dict) else None
    dims = dims if isinstance(dims, dict) else {}
    return {
        "length": _num(dims.get("length"), 0.0),
        "width": _num(dims.get("width"), 0.0),
        "height": _num(dims.get("height"), 0.0),
    }


def _classify(obj_type: str) -> str:
    t = (obj_type or "").strip().lower()
    for needles, role in _ROLE_RULES:
        if any(n in t for n in needles):
            return role
    return "furniture"


def _iter_objects(graph: dict[str, Any]) -> list[dict[str, Any]]:
    objs = graph.get("objects")
    return [o for o in objs if isinstance(o, dict)] if isinstance(objs, list) else []


# ── Normalization stages ─────────────────────────────────────────────────────


def _normalize_units(graph: dict[str, Any], report: dict[str, Any]) -> None:
    """Convert all linear values to metres and stamp an explicit unit."""
    site = graph.get("site")
    site = site if isinstance(site, dict) else {}
    unit = str(site.get("unit") or "metric").strip().lower()
    is_imperial = unit in {"imperial", "ft", "feet", "foot"}
    factor = FEET_TO_M if is_imperial else 1.0

    def _scale_dims(dims: Any) -> None:
        if not isinstance(dims, dict):
            return
        for key in ("length", "width", "height"):
            if key in dims and dims[key] is not None:
                dims[key] = round(_num(dims[key]) * factor, 4)
        dims["unit"] = "m"

    def _scale_pos(pos: Any) -> None:
        if not isinstance(pos, dict):
            return
        for key in ("x", "y", "z"):
            if key in pos and pos[key] is not None:
                pos[key] = round(_num(pos[key]) * factor, 4)

    # Room / spaces
    space = _primary_space(graph)
    if isinstance(space, dict):
        _scale_dims(space.get("dimensions"))
    if isinstance(graph.get("room"), dict):
        _scale_dims(graph["room"].get("dimensions"))

    for obj in _iter_objects(graph):
        _scale_dims(obj.get("dimensions"))
        _scale_pos(obj.get("position"))

    for light in graph.get("lighting", []) if isinstance(graph.get("lighting"), list) else []:
        if isinstance(light, dict):
            _scale_pos(light.get("position"))

    graph.setdefault("site", {})
    graph["site"]["unit"] = "metric"
    if is_imperial:
        report["corrections"].append(
            {"type": "unit", "detail": "Converted imperial (ft) values to metres."}
        )


def _normalize_axes(graph: dict[str, Any], report: dict[str, Any]) -> None:
    """Move depth out of ``position.y`` into ``position.z`` when collapsed.

    Canonical floor plane is (x, z). When a graph authors depth into ``y`` and
    leaves ``z`` at 0, the depth axis is "collapsed". We detect that by axis
    spread across furniture-like objects and swap y<->z for *all* object and
    lighting positions if so. Idempotent: a clean graph (z spread > 0) never
    swaps.
    """
    objs = _iter_objects(graph)
    positions = [o.get("position") for o in objs if isinstance(o.get("position"), dict)]
    if len(positions) < 2:
        return

    ys = [_num(p.get("y")) for p in positions]
    zs = [_num(p.get("z")) for p in positions]
    y_span = max(ys) - min(ys)
    z_span = max(zs) - min(zs)

    collapsed = (
        z_span < _AXIS_FLAT_EPS
        and y_span >= _AXIS_SWAP_MIN_SPAN
        and y_span > z_span
    )
    if not collapsed:
        return

    def _swap(pos: Any) -> None:
        if isinstance(pos, dict):
            pos["y"], pos["z"] = _num(pos.get("z")), _num(pos.get("y"))

    for obj in objs:
        _swap(obj.get("position"))
    for light in graph.get("lighting", []) if isinstance(graph.get("lighting"), list) else []:
        if isinstance(light, dict):
            _swap(light.get("position"))

    report["corrections"].append(
        {
            "type": "axis",
            "detail": (
                f"Depth axis was collapsed (z-span={z_span:.2f}m, y-span={y_span:.2f}m); "
                "swapped y<->z so depth lives on z."
            ),
        }
    )


def _clamp(value: float, lo: float, hi: float) -> float:
    if hi < lo:
        return lo
    return max(lo, min(hi, value))


def _normalize_object_dimensions(graph: dict[str, Any], report: dict[str, Any]) -> None:
    """Scale oversized footprints to fit and clamp centres inside the room."""
    room = _room_dimensions(graph)
    room_l, room_w = room["length"], room["width"]
    if room_l <= 0 or room_w <= 0:
        return
    room_area = room_l * room_w

    for obj in _iter_objects(graph):
        dims = obj.get("dimensions")
        if not isinstance(dims, dict):
            continue
        role = obj.get("role") or _classify(str(obj.get("type") or ""))

        width = max(_num(dims.get("width"), _MIN_EXTENT), _MIN_EXTENT)
        length = max(_num(dims.get("length"), _MIN_EXTENT), _MIN_EXTENT)

        # Edge elements (walls/windows/doors) legitimately span a full wall —
        # only furniture/decor footprints get the area cap.
        scaled = False
        max_w = room_l * _MAX_EXTENT_FRACTION
        max_l = room_w * _MAX_EXTENT_FRACTION
        if width > max_w:
            width, scaled = max_w, True
        if length > max_l:
            length, scaled = max_l, True

        if role not in _EDGE_ROLES:
            footprint = width * length
            cap = room_area * _MAX_FOOTPRINT_FRACTION
            if footprint > cap and footprint > 0:
                shrink = (cap / footprint) ** 0.5
                width *= shrink
                length *= shrink
                scaled = True

        if scaled:
            dims["width"] = round(width, 4)
            dims["length"] = round(length, 4)
            report["corrections"].append(
                {
                    "type": "dimension",
                    "object_id": obj.get("id"),
                    "detail": f"Scaled oversized footprint to fit room ({room_l:.1f}×{room_w:.1f}m).",
                }
            )

        # Clamp centre so the bounding box stays inside the room. Edge
        # elements (walls/windows/doors) legitimately sit ON the boundary —
        # they were snapped to a wall already, so don't pull them back in.
        pos = obj.get("position")
        if isinstance(pos, dict) and role not in _EDGE_ROLES:
            half_w, half_l = width / 2, length / 2
            new_x = _clamp(_num(pos.get("x")), half_w, room_l - half_w)
            new_z = _clamp(_num(pos.get("z")), half_l, room_w - half_l)
            if (round(new_x, 3), round(new_z, 3)) != (
                round(_num(pos.get("x")), 3),
                round(_num(pos.get("z")), 3),
            ):
                report["corrections"].append(
                    {
                        "type": "position",
                        "object_id": obj.get("id"),
                        "detail": "Clamped object inside room bounds.",
                    }
                )
            pos["x"], pos["z"] = round(new_x, 4), round(new_z, 4)


def _classify_and_snap(graph: dict[str, Any], report: dict[str, Any]) -> None:
    """Stamp ``role`` on every object and snap edge elements to walls."""
    room = _room_dimensions(graph)
    room_l, room_w = room["length"], room["width"]

    for obj in _iter_objects(graph):
        role = _classify(str(obj.get("type") or ""))
        obj["role"] = role

        if role not in _EDGE_ROLES or room_l <= 0 or room_w <= 0:
            continue
        pos = obj.get("position")
        if not isinstance(pos, dict):
            continue
        x, z = _num(pos.get("x")), _num(pos.get("z"))
        # Distance to each of the four walls; snap the nearer axis to its edge.
        d_left, d_right = x, room_l - x
        d_top, d_bottom = z, room_w - z
        nearest = min(d_left, d_right, d_top, d_bottom)
        if nearest == d_left:
            pos["x"] = _EDGE_INSET
        elif nearest == d_right:
            pos["x"] = round(room_l - _EDGE_INSET, 4)
        elif nearest == d_top:
            pos["z"] = _EDGE_INSET
        else:
            pos["z"] = round(room_w - _EDGE_INSET, 4)


# ── Public API ───────────────────────────────────────────────────────────────


def normalize_graph(raw_graph: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return ``(clean_graph, report)`` for a raw design graph.

    Never mutates the input. ``report`` carries the list of corrections plus
    the validation result of the cleaned graph. Safe and idempotent to run on
    every save.
    """
    if not isinstance(raw_graph, dict):
        return raw_graph, {"ok": False, "corrections": [], "errors": ["graph is not an object"], "warnings": []}

    graph = copy.deepcopy(raw_graph)
    report: dict[str, Any] = {"corrections": [], "errors": [], "warnings": []}

    _normalize_units(graph, report)
    _normalize_axes(graph, report)
    _classify_and_snap(graph, report)
    _normalize_object_dimensions(graph, report)

    validation = validate_graph(graph)
    report["ok"] = validation["ok"]
    report["errors"] = validation["errors"]
    report["warnings"] = validation["warnings"]
    return graph, report


def validate_graph(graph: dict[str, Any]) -> dict[str, Any]:
    """Assert the canonical invariants on an (already normalized) graph.

    Returns ``{ok, errors, warnings}``. Errors mean the graph still violates a
    hard invariant after normalization (a bug worth surfacing loudly);
    warnings are advisory (e.g. an empty room, suspicious overlaps).
    """
    errors: list[str] = []
    warnings: list[str] = []

    room = _room_dimensions(graph)
    room_l, room_w, room_h = room["length"], room["width"], room["height"]
    if room_l <= 0 or room_w <= 0:
        errors.append("Room has non-positive length/width.")
    if room_h <= 0:
        warnings.append("Room height missing or non-positive.")

    site = graph.get("site")
    if not (isinstance(site, dict) and site.get("unit") == "metric"):
        errors.append("site.unit is not canonical 'metric'.")

    objs = _iter_objects(graph)
    if not objs:
        warnings.append("Graph has no objects.")

    footprint_total = 0.0
    for obj in objs:
        oid = obj.get("id") or "?"
        pos = obj.get("position")
        dims = obj.get("dimensions")
        if not isinstance(pos, dict):
            errors.append(f"Object {oid} has no position.")
            continue
        x, y, z = _num(pos.get("x")), _num(pos.get("y")), _num(pos.get("z"))
        if any(v != v for v in (x, y, z)):  # NaN
            errors.append(f"Object {oid} has NaN coordinates.")
        role = obj.get("role") or _classify(str(obj.get("type") or ""))
        if isinstance(dims, dict):
            if dims.get("unit") != "m":
                warnings.append(f"Object {oid} dimensions not stamped in metres.")
            w = _num(dims.get("width"))
            ln = _num(dims.get("length"))
            footprint_total += max(w, 0) * max(ln, 0)
            # Edge elements (walls/windows/doors) sit ON the boundary by
            # design, so their footprint legitimately touches/crosses a wall
            # line — only furniture/decor must be fully inside.
            if room_l > 0 and room_w > 0 and role not in _EDGE_ROLES:
                half_w, half_l = w / 2, ln / 2
                if x + half_w > room_l + 1e-3 or x - half_w < -1e-3:
                    errors.append(f"Object {oid} extends beyond room on x.")
                if z + half_l > room_w + 1e-3 or z - half_l < -1e-3:
                    errors.append(f"Object {oid} extends beyond room on z.")

    # Axis-collapse smell: many objects but no depth spread.
    if len(objs) >= 2:
        zs = [_num(o.get("position", {}).get("z")) for o in objs if isinstance(o.get("position"), dict)]
        if zs and (max(zs) - min(zs)) < _AXIS_FLAT_EPS:
            warnings.append("Objects show almost no depth spread (possible axis collapse).")

    if room_l > 0 and room_w > 0 and footprint_total > room_l * room_w:
        warnings.append("Total furniture footprint exceeds room floor area.")

    return {"ok": not errors, "errors": errors, "warnings": warnings}
