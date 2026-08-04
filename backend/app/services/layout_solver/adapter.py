"""Bridge between the loose ``DesignGraph`` and the typed solver.

This is deliberately thin and side-effect-light. It lets the solver run against
the real data shape today; wiring it into ``generation_pipeline`` (and teaching
the kernel / wall model / drawings to consume multiple rooms) is the next
increment, so ``apply_layout_to_graph`` is written to be *additive* — it fills
in room positions/dimensions without destroying anything the graph already has.
"""

from __future__ import annotations

from typing import Any

from .models import LayoutProgram, LayoutSolution, RoomSpec

_DEFAULT_ROOM_AREA = 12.0   # m², a small habitable room, when nothing is stated
_DEFAULT_HEIGHT = 2.8       # m


def _mm(value: float) -> float:
    """Snap a metre value to the 1 mm grid (spec-level, docs trap #5/#7)."""
    return round(value, 3)


def _to_m(value: Any) -> float:
    """Best-effort length → metres (mirrors the resolver's mm heuristic)."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return 0.0
    return n / 1000.0 if abs(n) > 30 else n  # a "4500" is mm; a "4.5" is metres


def _room_area(space: dict) -> tuple[float, bool]:
    """Return ``(area_m², stated)``. ``stated`` is False when the graph gave us
    nothing to go on and we fell back to the default — the caller surfaces that."""
    dims = space.get("dimensions") if isinstance(space, dict) else None
    if isinstance(dims, dict):
        length, width = _to_m(dims.get("length")), _to_m(dims.get("width"))
        if length > 0 and width > 0:
            return length * width, True
    area = space.get("area") if isinstance(space, dict) else None
    try:
        a = float(area)
        if a > 0:
            return a, True
    except (TypeError, ValueError):
        pass
    return _DEFAULT_ROOM_AREA, False


def program_from_graph(graph: dict, **overrides: Any) -> LayoutProgram:
    """Read a ``DesignGraph``-shaped dict into a solver program.

    Rooms come from ``graph['spaces']``. Adjacencies come from
    ``graph['adjacencies']`` (list of ``{"a","b"}`` or ``[a, b]`` pairs) when
    present. ``overrides`` (seed, iterations, boundary, boundary_aspect) pass
    straight through to :class:`LayoutProgram`.
    """
    spaces = graph.get("spaces") if isinstance(graph, dict) else None
    rooms: list[RoomSpec] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for i, space in enumerate(spaces or []):
        if not isinstance(space, dict):
            continue
        rid = str(space.get("id") or space.get("name") or f"space_{i + 1}")
        if rid in seen:  # ids must be unique for the solver's dicts
            rid = f"{rid}_{i + 1}"
        seen.add(rid)
        area, stated = _room_area(space)
        rooms.append(RoomSpec(id=rid, name=str(space.get("name") or rid), area=area))
        if not stated:
            warnings.append(
                f"room '{rid}' had no stated area; assumed {_DEFAULT_ROOM_AREA:g} m² — "
                f"provide it in the brief so the plan rests on the design, not a default"
            )

    adjacencies: list[tuple[str, str]] = []
    for pair in (graph.get("adjacencies") or []) if isinstance(graph, dict) else []:
        a = b = None
        if isinstance(pair, dict):
            a, b = pair.get("a"), pair.get("b")
        elif isinstance(pair, (list, tuple)) and len(pair) >= 2:
            a, b = pair[0], pair[1]
        if a and b:
            adjacencies.append((str(a), str(b)))

    return LayoutProgram(rooms=rooms, adjacencies=adjacencies, warnings=warnings, **overrides)


def apply_layout_to_graph(graph: dict, solution: LayoutSolution) -> dict:
    """Return a copy of ``graph`` with solved room rectangles written back.

    Each placed room is matched into ``spaces`` by id and given a ``position``
    (min corner, y=0) and ``dimensions`` (length/width, preserving any existing
    height). The site ``boundary`` is recorded at the top level. Non-destructive:
    unrelated fields and unmatched spaces are left untouched.
    """
    out = dict(graph or {})
    spaces = [dict(s) if isinstance(s, dict) else s for s in (out.get("spaces") or [])]
    by_id = {str(s.get("id") or s.get("name")): s for s in spaces if isinstance(s, dict)}

    for room in solution.rooms:
        target = by_id.get(room.id)
        if target is None:
            target = {"id": room.id, "name": room.name}
            spaces.append(target)
            by_id[room.id] = target
        existing_dims = target.get("dimensions") if isinstance(target.get("dimensions"), dict) else {}
        height = _to_m(existing_dims.get("height")) or _DEFAULT_HEIGHT
        # Snap to the 1 mm spec grid here — the "convert at the boundary" step.
        target["position"] = {"x": _mm(room.x), "y": 0.0, "z": _mm(room.z)}
        target["dimensions"] = {
            "length": _mm(room.length),
            "width": _mm(room.width),
            "height": _mm(height),
            "unit": "m",
        }

    out["spaces"] = spaces
    out["boundary"] = {"length": _mm(solution.boundary[0]), "width": _mm(solution.boundary[1]), "unit": "m"}
    return out
