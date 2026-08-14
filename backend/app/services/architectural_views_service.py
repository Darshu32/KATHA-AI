"""Deterministic, graph-driven *architectural* working views.

Phase-2 re-domaining of Section / Elevation / Isometric / Detail away from the
furniture-piece generators (seat depth, joinery, foam layers) toward the actual
room the user designed. These render straight from the **normalized** design
graph (see ``graph_normalizer``) — so depth lives on ``z``, units are metres,
objects carry a ``role`` (wall / window / door / furniture / …), and everything
sits inside the room envelope.

Why deterministic (no LLM here): the user's complaint was that the views did
not reflect *their* design. A renderer reading the graph directly is faithful
by construction, free, fast, and unit-testable. The LLM furniture-spec services
remain available for the furniture/manufacturing workflow
(``working_drawings.py`` POST endpoints); this module powers the room-scale
``/design`` Views tab via ``drawings.py`` GET routes.

Coordinate model (post-normalization, metric):
    room: length ``L`` spans x, width ``W`` spans z (floor plane), height ``H`` is y.
    object: position {x, z} on the floor, y≈0; dimensions {width=dx, length=dz, height=dy}.
"""

from __future__ import annotations

import logging
from html import escape
from typing import Any

from app.services.spatial.graph_geometry import (
    Rect,
    assign_objects,
    bbox_of_rects,
    depictable_objects,
    layout_rooms,
    object_rect,
    room_id,
    room_name,
    room_rect,
)
from app.services.wall_model import derive_multiroom_wall_model

logger = logging.getLogger(__name__)

CW = 960
CH = 640
PAD = 64

# Warm paper palette — consistent with the floor-plan preview.
_PAPER = "#fcf7ef"
_GRID = "#eadfce"
_INK = "#4c3d30"
_INK_SOFT = "#9d8a75"
_POCHE = "#6d5743"
_FILL = "#d9c7b1"
_OPENING = "#96bfd0"
_DOOR = "#8b5e3c"
_DIM = "#b8a591"


# ── Graph access helpers ─────────────────────────────────────────────────────


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out else default


def _primary_space(graph: dict) -> dict:
    spaces = graph.get("spaces")
    if isinstance(spaces, list) and spaces and isinstance(spaces[0], dict):
        return spaces[0]
    room = graph.get("room")
    return room if isinstance(room, dict) else {}


def _room(graph: dict) -> tuple[float, float, float]:
    dims = (_primary_space(graph).get("dimensions") or {}) if graph else {}
    L = max(_num(dims.get("length"), 6.0), 0.5)
    W = max(_num(dims.get("width"), 4.0), 0.5)
    H = max(_num(dims.get("height"), 2.7), 0.5)
    return L, W, H


def _objects(graph: dict) -> list[dict]:
    objs = graph.get("objects") if isinstance(graph, dict) else None
    return [o for o in objs if isinstance(o, dict)] if isinstance(objs, list) else []


def _obj_box(o: dict) -> dict:
    pos = o.get("position") or {}
    dim = o.get("dimensions") or {}
    return {
        "id": o.get("id") or "obj",
        "type": str(o.get("type") or "object"),
        "name": str(o.get("name") or o.get("type") or "object"),
        "role": str(o.get("role") or "furniture"),
        "x": _num(pos.get("x")),
        "z": _num(pos.get("z")),
        "y": _num(pos.get("y")),
        "dx": max(_num(dim.get("width"), 0.5), 0.05),
        "dz": max(_num(dim.get("length"), 0.5), 0.05),
        "dy": max(_num(dim.get("height"), 0.5), 0.05),
    }


def _room_type(graph: dict) -> str:
    sp = _primary_space(graph)
    return str(sp.get("room_type") or sp.get("name") or graph.get("design_type") or "space")


def _label(text: str) -> str:
    return escape(text.replace("_", " ").title())


def _clamp_rect(r: Rect, room: Rect) -> Rect:
    """Fit an object's footprint + height inside a room's envelope: slide a piece
    that crosses a wall back inside, cap one larger than the room. Stops furniture
    and openings being drawn through walls or hanging off the floor — the same
    envelope guarantee the plan preview applies (bad upstream placement is the
    real cause; this keeps every view honest until it's fixed at the source)."""
    def fit(a0: float, a1: float, lo: float, hi: float) -> tuple[float, float]:
        span = a1 - a0
        if span >= (hi - lo):
            return lo, hi
        if a0 < lo:
            return lo, lo + span
        if a1 > hi:
            return hi - span, hi
        return a0, a1

    x0, x1 = fit(r.x0, r.x1, room.x0, room.x1)
    z0, z1 = fit(r.z0, r.z1, room.z0, room.z1)
    y0, y1 = fit(r.y0, r.y1, 0.0, max(room.y1, 0.05))
    return Rect(x0, x1, z0, z1, y0, y1)


# ── Shared SVG scaffold ──────────────────────────────────────────────────────


def _svg_open(title: str, subtitle: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {CW} {CH}" fill="none">',
        f'<rect width="100%" height="100%" rx="28" fill="{_PAPER}"/>',
        '<defs>'
        '<pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">'
        f'<path d="M 24 0 L 0 0 0 24" stroke="{_GRID}" stroke-width="1"/></pattern>'
        f'<pattern id="poche" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
        f'<line x1="0" y1="0" x2="0" y2="6" stroke="{_POCHE}" stroke-width="1.4"/></pattern>'
        '</defs>',
        f'<rect x="0" y="0" width="{CW}" height="{CH}" fill="url(#grid)"/>',
        f'<text x="{PAD}" y="36" fill="{_INK}" font-size="17" font-weight="700">{escape(title)}</text>',
        f'<text x="{PAD}" y="57" fill="{_INK_SOFT}" font-size="13">{escape(subtitle)}</text>',
    ]


def _hdim(x1: float, x2: float, y: float, text: str) -> str:
    """Horizontal dimension line with end ticks and centred label."""
    mid = (x1 + x2) / 2
    return (
        f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" stroke="{_DIM}" stroke-width="1.4"/>'
        f'<line x1="{x1:.1f}" y1="{y-4:.1f}" x2="{x1:.1f}" y2="{y+4:.1f}" stroke="{_DIM}" stroke-width="1.4"/>'
        f'<line x1="{x2:.1f}" y1="{y-4:.1f}" x2="{x2:.1f}" y2="{y+4:.1f}" stroke="{_DIM}" stroke-width="1.4"/>'
        f'<text x="{mid:.1f}" y="{y-6:.1f}" text-anchor="middle" fill="#8b755f" font-size="12">{escape(text)}</text>'
    )


def _vdim(y1: float, y2: float, x: float, text: str) -> str:
    """Vertical dimension line with end ticks and rotated label."""
    mid = (y1 + y2) / 2
    return (
        f'<line x1="{x:.1f}" y1="{y1:.1f}" x2="{x:.1f}" y2="{y2:.1f}" stroke="{_DIM}" stroke-width="1.4"/>'
        f'<line x1="{x-4:.1f}" y1="{y1:.1f}" x2="{x+4:.1f}" y2="{y1:.1f}" stroke="{_DIM}" stroke-width="1.4"/>'
        f'<line x1="{x-4:.1f}" y1="{y2:.1f}" x2="{x+4:.1f}" y2="{y2:.1f}" stroke="{_DIM}" stroke-width="1.4"/>'
        f'<text x="{x-8:.1f}" y="{mid:.1f}" text-anchor="middle" fill="#8b755f" font-size="12" '
        f'transform="rotate(-90 {x-8:.1f} {mid:.1f})">{escape(text)}</text>'
    )


# ── Section view ─────────────────────────────────────────────────────────────


def generate_section_package(
    graph: dict, cut_axis: str | None = None, cut_at: float | None = None
) -> dict:
    """Building cross-section through the placed rooms.

    A single vertical cut plane — perpendicular to z by default — is positioned
    to pass through the most rooms (tie broken toward the building centre). Only
    the rooms it crosses are drawn, left to right, each with its floor line,
    ceiling line and cut side-walls in poché; a wall two adjacent rooms share is
    drawn once. Furniture the plane passes through is drawn solid, furniture in a
    cut room that the plane misses is ghosted, and objects in rooms outside the
    cut are accounted for (placements) but not drawn. ``cut_axis`` ('x'|'z') and
    ``cut_at`` (metres) override the computed default so a later UI can pick the
    line without any backend change.
    """
    rooms = layout_rooms(graph)
    room_specs = [(room_id(s, i), room_name(s, i), room_rect(s)) for i, s in enumerate(rooms)]
    depictable = depictable_objects(graph)
    by_room, orphans = assign_objects(graph, objects=depictable, rooms=rooms)
    bb = bbox_of_rects([r for _, _, r in room_specs])

    axis = (cut_axis or "z").lower()
    if axis not in ("x", "z"):
        axis = "z"

    # In-plane horizontal coord u (x when cutting ⊥z, else z); depth is the axis.
    def u_span(r: Rect) -> tuple[float, float]:
        return (r.x0, r.x1) if axis == "z" else (r.z0, r.z1)

    def depth_span(r: Rect) -> tuple[float, float]:
        return (r.z0, r.z1) if axis == "z" else (r.x0, r.x1)

    if not room_specs or bb is None:
        seg = _svg_open("Section", "No placed rooms to cut")
        seg.append("</svg>")
        return {
            "drawing_type": "section_view", "preview_svg": "".join(seg), "placements": [],
            "summary": {"cut_axis": axis, "cut_at_m": 0.0, "ceiling_height_m": 0.0,
                        "rooms_in_cut": 0, "rooms_total": 0, "objects_cut": 0,
                        "objects_behind": 0, "openings": 0},
        }

    cut = _choose_cut(room_specs, axis, cut_at, bb)
    cut_rooms = sorted(
        [rs for rs in room_specs if depth_span(rs[2])[0] <= cut < depth_span(rs[2])[1]],
        key=lambda t: u_span(t[2])[0],
    )
    if not cut_rooms:  # an explicit cut_at that missed every room
        cut_rooms = sorted(room_specs, key=lambda t: u_span(t[2])[0])
    cut_room_ids = {rid for rid, _, _ in cut_rooms}

    u0 = min(u_span(r)[0] for _, _, r in cut_rooms)
    u1 = max(u_span(r)[1] for _, _, r in cut_rooms)
    Hmax = max(r.y1 for _, _, r in cut_rooms)
    span_u = (u1 - u0) or 1.0

    plot_w, plot_h = CW - PAD * 2, CH - PAD * 2 - 30
    s = min(plot_w / span_u, plot_h / Hmax)
    ox = PAD + (plot_w - span_u * s) / 2
    floor_y = PAD + 30 + Hmax * s  # y grows downward in SVG; floor at bottom

    def px(u: float) -> float:
        return ox + (u - u0) * s

    def py(y: float) -> float:
        return floor_y - y * s

    title = _label(room_specs[0][1]) if len(room_specs) == 1 else _label(str(graph.get("design_type") or "Floor Plate"))
    seg = _svg_open(
        f"Section — {title}",
        f"Cut ⊥ {axis} at {cut:.2f} m · {len(cut_rooms)} of {len(room_specs)} room"
        f"{'s' if len(room_specs) != 1 else ''} · ceiling {Hmax:.2f} m · width {span_u:.2f} m",
    )

    # Floor line spanning the whole cut.
    seg.append(f'<line x1="{px(u0):.1f}" y1="{floor_y:.1f}" x2="{px(u1):.1f}" y2="{floor_y:.1f}" stroke="{_INK}" stroke-width="3"/>')

    # Ceiling line + name per room; poché side walls, sharing deduplicated by u.
    wall_heights: dict[float, float] = {}
    for _rid, name, r in cut_rooms:
        ru0, ru1 = u_span(r)
        H = r.y1
        seg.append(f'<line x1="{px(ru0):.1f}" y1="{py(H):.1f}" x2="{px(ru1):.1f}" y2="{py(H):.1f}" stroke="{_INK}" stroke-width="2"/>')
        seg.append(f'<text x="{(px(ru0)+px(ru1))/2:.1f}" y="{py(H)+16:.1f}" text-anchor="middle" fill="{_INK}" font-size="11" font-weight="700">{escape(name[:18])}</text>')
        for u in (ru0, ru1):
            k = round(u, 3)
            wall_heights[k] = max(wall_heights.get(k, 0.0), H)
    wall_t = max(0.1 * s, 6)  # ~100 mm poché
    for u, H in wall_heights.items():
        seg.append(f'<rect x="{px(u)-wall_t/2:.1f}" y="{py(H):.1f}" width="{wall_t:.1f}" height="{H*s:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.4"/>')

    # Objects: solid if the plane passes through, ghosted if behind, in cut rooms.
    cut_ids, behind_ids, off_ids = [], [], []
    for rid, _name, _r in cut_rooms:
        for o in by_room.get(rid, []):
            orc = _clamp_rect(object_rect(o), _r)
            ou0, ou1 = (orc.x0, orc.x1) if axis == "z" else (orc.z0, orc.z1)
            od0, od1 = depth_span(orc)
            h = orc.y1
            if od0 <= cut <= od1:  # plane passes through the piece
                role = str(o.get("role") or "").lower()
                fill = _OPENING if role == "window" else _DOOR if role == "door" else _FILL
                seg.append(f'<rect x="{px(ou0):.1f}" y="{floor_y-h*s:.1f}" width="{(ou1-ou0)*s:.1f}" height="{h*s:.1f}" rx="3" fill="{fill}" stroke="{_POCHE}" stroke-width="2"/>')
                seg.append(f'<text x="{(px(ou0)+px(ou1))/2:.1f}" y="{floor_y-h*s-4:.1f}" text-anchor="middle" fill="#2c221a" font-size="9">{_label(str(o.get("name") or o.get("type") or "item"))[:14]}</text>')
                cut_ids.append(o.get("id"))
            else:  # in a cut room but the plane misses it — ghost behind
                seg.append(f'<rect x="{px(ou0):.1f}" y="{floor_y-h*s:.1f}" width="{(ou1-ou0)*s:.1f}" height="{h*s:.1f}" fill="none" stroke="{_INK_SOFT}" stroke-width="1.1" stroke-dasharray="4 3"/>')
                behind_ids.append(o.get("id"))
    for rid, objs in by_room.items():
        if rid not in cut_room_ids:
            off_ids.extend(o.get("id") for o in objs)
    off_ids.extend(o.get("id") for o in orphans)

    # Dimensions.
    seg.append(_vdim(py(Hmax), floor_y, px(u0) - 16, f"{Hmax:.2f} m"))
    seg.append(_hdim(px(u0), px(u1), floor_y + 34, f"{span_u:.2f} m"))
    seg.append("</svg>")

    placements = (
        [{"id": i, "mode": "cut"} for i in cut_ids]
        + [{"id": i, "mode": "behind"} for i in behind_ids]
        + [{"id": i, "mode": "off_cut"} for i in off_ids]
    )
    openings = sum(1 for o in depictable if str(o.get("role") or "").lower() in ("window", "door"))
    return {
        "drawing_type": "section_view",
        "preview_svg": "".join(seg),
        "placements": placements,
        "summary": {
            "cut_axis": axis,
            "cut_at_m": round(cut, 2),
            "ceiling_height_m": round(Hmax, 2),
            "rooms_in_cut": len(cut_rooms),
            "rooms_total": len(room_specs),
            "objects_cut": len(cut_ids),
            "objects_behind": len(behind_ids),
            "openings": openings,
        },
    }


def _choose_cut(room_specs: list, axis: str, cut_at: float | None, bb: Rect) -> float:
    """Cut position that passes through the most rooms; tie → nearest bbox centre.

    Candidates are each room's mid-depth; ``cut_at`` (metres) overrides. Depth is
    z when cutting ⊥z (the default), else x.
    """
    if cut_at is not None:
        return float(cut_at)

    def depth_span(r: Rect) -> tuple[float, float]:
        return (r.z0, r.z1) if axis == "z" else (r.x0, r.x1)

    centre = (bb.z0 + bb.z1) / 2 if axis == "z" else (bb.x0 + bb.x1) / 2
    candidates = [sum(depth_span(r)) / 2 for _, _, r in room_specs]
    if not candidates:
        return centre

    def count_through(z: float) -> int:
        return sum(1 for _, _, r in room_specs if depth_span(r)[0] <= z < depth_span(r)[1])

    return max(candidates, key=lambda z: (count_through(z), -abs(z - centre)))


# ── Elevation view ───────────────────────────────────────────────────────────


def _draw_opening(out: list[str], x: float, top: float, w: float, h: float, kind: str) -> None:
    """One opening on an elevation face — a framed reveal, glazed with a mullion
    for a window, a filled leaf for a door."""
    out.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{_PAPER}" stroke="{_INK}" stroke-width="1.8"/>')
    if kind == "door":
        out.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{_DOOR}" fill-opacity="0.22"/>')
    else:
        out.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{_OPENING}" fill-opacity="0.28"/>')
        out.append(f'<line x1="{x+w/2:.1f}" y1="{top:.1f}" x2="{x+w/2:.1f}" y2="{top+h:.1f}" stroke="{_INK}" stroke-width="1" stroke-opacity="0.7"/>')


def generate_elevation_package(graph: dict, face: str | None = None) -> dict:
    """Exterior building elevation — every placed room projected onto one face.

    The longest side faces the viewer by default (``face`` = north|south|east|
    west overrides; north/south look along z with x horizontal, east/west look
    along x with z horizontal). Each room projects to a width×height block; their
    union is the building silhouette, so rooms of different heights read as a
    stepped roofline. Windows and doors are shown on the face (they are what you
    see on an elevation); interior furniture is not drawn on an exterior
    elevation, but every object is still listed in ``placements`` so nothing a
    user designed is silently lost. ``face`` is wired for a later UI picker.
    """
    rooms = layout_rooms(graph)
    room_specs = [(room_id(s, i), room_name(s, i), room_rect(s)) for i, s in enumerate(rooms)]
    depictable = depictable_objects(graph)
    bb = bbox_of_rects([r for _, _, r in room_specs])

    if not room_specs or bb is None:
        seg = _svg_open("Elevation", "No placed rooms to project")
        seg.append("</svg>")
        return {
            "drawing_type": "elevation_view", "preview_svg": "".join(seg), "placements": [],
            "summary": {"face": "south", "wall_length_m": 0.0, "wall_height_m": 0.0, "openings": 0},
        }

    f = (face or "").lower()
    if f in ("north", "south"):
        axis = "z"
    elif f in ("east", "west"):
        axis = "x"
    else:  # default: the longest side faces the viewer
        axis = "z" if (bb.x1 - bb.x0) >= (bb.z1 - bb.z0) else "x"
        f = "south" if axis == "z" else "west"

    def u_span(r: Rect) -> tuple[float, float]:
        return (r.x0, r.x1) if axis == "z" else (r.z0, r.z1)

    u0, u1 = (bb.x0, bb.x1) if axis == "z" else (bb.z0, bb.z1)
    Hmax = bb.y1
    span_u = (u1 - u0) or 1.0

    plot_w, plot_h = CW - PAD * 2, CH - PAD * 2 - 30
    s = min(plot_w / span_u, plot_h / Hmax)
    ox = PAD + (plot_w - span_u * s) / 2
    ground = PAD + 30 + Hmax * s

    def ux(u: float) -> float:
        return ox + (u - u0) * s

    def hy(h: float) -> float:
        return ground - h * s

    title = _label(room_specs[0][1]) if len(room_specs) == 1 else _label(str(graph.get("design_type") or "Floor Plate"))
    seg = _svg_open(
        f"{f.title()} Elevation — {title}",
        f"Building elevation · {len(room_specs)} room{'s' if len(room_specs) != 1 else ''} · "
        f"width {span_u:.2f} m · height {Hmax:.2f} m",
    )

    # Ground line, then each room as a silhouette block (stepped roofline).
    seg.append(f'<line x1="{ux(u0)-10:.1f}" y1="{ground:.1f}" x2="{ux(u1)+10:.1f}" y2="{ground:.1f}" stroke="{_INK}" stroke-width="2.5"/>')
    for _rid, _name, r in sorted(room_specs, key=lambda t: u_span(t[2])[0]):
        ru0, ru1 = u_span(r)
        H = r.y1
        seg.append(f'<rect x="{ux(ru0):.1f}" y="{hy(H):.1f}" width="{(ru1-ru0)*s:.1f}" height="{H*s:.1f}" fill="#f6ede0" stroke="{_INK}" stroke-width="2"/>')

    # Openings on the face. Prefer real window/door OBJECTS from the graph; when
    # it carries none — multi-room plans synthesise openings in the wall model,
    # not as objects — fall back to the wall model's windows on the face-parallel
    # exterior walls, so the facade is never drawn blank.
    openings = 0
    opening_objs = [o for o in depictable if str(o.get("role") or "").lower() in ("window", "door")]
    if opening_objs:
        for o in opening_objs:
            if str(o.get("wall") or "") == "partition":
                continue  # a derived interior door — not shown on an exterior elevation
            role = str(o.get("role") or "").lower()
            orc = _clamp_rect(object_rect(o), bb)
            ou0, ou1 = (orc.x0, orc.x1) if axis == "z" else (orc.z0, orc.z1)
            sill = max(_num((o.get("position") or {}).get("y"), 0.0), 0.0)
            head = min(sill + orc.y1, Hmax)
            x, w = ux(ou0), max((ou1 - ou0) * s, 2.0)
            top, h = hy(head), max((head - sill) * s, 2.0)
            _draw_opening(seg, x, top, w, h, role)
            openings += 1
    else:
        face_run = "x" if axis == "z" else "z"  # walls parallel to the drawn face
        wm_rooms = [{"id": rid, "x": r.x0, "z": r.z0, "length": r.x1 - r.x0,
                     "width": r.z1 - r.z0, "height": r.y1} for rid, _nm, r in room_specs]
        for wseg in derive_multiroom_wall_model(wm_rooms, graph.get("adjacencies")):
            if wseg.get("kind") != "exterior" or wseg.get("runs") != face_run:
                continue
            for op in wseg.get("openings", []):
                uc = wseg["start"] + op["center"]
                ua, ub = uc - op["width"] / 2, uc + op["width"] / 2
                sill, head = op["sill"], min(op["head"], Hmax)
                x, w = ux(ua), max((ub - ua) * s, 2.0)
                top, h = hy(head), max((head - sill) * s, 2.0)
                _draw_opening(seg, x, top, w, h, op.get("kind", "window"))
                openings += 1

    seg.append(_hdim(ux(u0), ux(u1), ground + 20, f"{span_u:.2f} m"))
    seg.append(_vdim(hy(Hmax), ground, ux(u0) - 14, f"{Hmax:.2f} m"))
    seg.append("</svg>")

    placements = [
        {"id": o.get("id"), "role": str(o.get("role") or "").lower(),
         "mode": "opening" if str(o.get("role") or "").lower() in ("window", "door") else "concealed"}
        for o in depictable
    ]
    return {
        "drawing_type": "elevation_view",
        "preview_svg": "".join(seg),
        "placements": placements,
        "summary": {
            "face": f,
            "wall_length_m": round(span_u, 2),
            "wall_height_m": round(Hmax, 2),
            "openings": openings,
        },
    }


# ── Isometric view ───────────────────────────────────────────────────────────


_COS30 = 0.8660254
_SIN30 = 0.5


def generate_isometric_package(graph: dict) -> dict:
    """Axonometric massing of every placed room + its furniture.

    Rooms are drawn back-to-front (painter's order, ascending x0+z0) so a nearer
    room occludes a farther one, and each room's furniture is emitted
    immediately after its own box — never all rooms then all furniture — so a
    piece can never float over the wrong room. Furniture whose centre lands in no
    room is logged and omitted rather than misplaced (the failure mode of the
    old spaces[0] renderer). Multi-room aware; a single-room graph collapses to
    one box with identical envelope figures.
    """
    rooms = layout_rooms(graph)
    room_specs = [(room_id(s, i), room_name(s, i), room_rect(s)) for i, s in enumerate(rooms)]
    # Depict every non-wall object (furniture AND openings) so nothing a user
    # designed is dropped; assign each to the room holding its centre.
    depictable = depictable_objects(graph)
    by_room, orphans = assign_objects(graph, objects=depictable, rooms=rooms)
    if orphans:
        logger.warning(
            "isometric_orphan_objects",
            extra={"count": len(orphans), "ids": [o.get("id") for o in orphans][:8]},
        )

    bb = bbox_of_rects([r for _, _, r in room_specs]) or Rect(0.0, 6.0, 0.0, 4.5, 0.0, 2.9)

    # Iso projection (metres → screen units, before pixel scale).
    def iso(x: float, y: float, z: float) -> tuple[float, float]:
        return (x - z) * _COS30, (x + z) * _SIN30 - y

    # Scale to fit every room. Both in-room objects and orphans are clamped to an
    # envelope (their room, or the building bbox) at draw time, so everything
    # drawn lands inside the rooms' union and no extra allowance is needed here.
    corners = [
        iso(X, Y, Z)
        for r in [r for _, _, r in room_specs]
        for X in (r.x0, r.x1) for Y in (r.y0, r.y1) for Z in (r.z0, r.z1)
    ]
    xs = [c[0] for c in corners] or [0.0]
    ys = [c[1] for c in corners] or [0.0]
    span_x = (max(xs) - min(xs)) or 1.0
    span_y = (max(ys) - min(ys)) or 1.0
    plot_w, plot_h = CW - PAD * 2, CH - PAD * 2 - 30
    s = min(plot_w / span_x, plot_h / span_y)
    ox = PAD + (plot_w - span_x * s) / 2 - min(xs) * s
    oy = PAD + 30 + (plot_h - span_y * s) / 2 - min(ys) * s

    def sp(x: float, y: float, z: float) -> tuple[float, float]:
        ix, iy = iso(x, y, z)
        return ox + ix * s, oy + iy * s

    bw, bd, bh = bb.x1 - bb.x0, bb.z1 - bb.z0, bb.y1
    n = len(room_specs)
    title = _label(room_specs[0][1]) if n == 1 else _label(str(graph.get("design_type") or "Floor Plate"))
    seg = _svg_open(
        f"Isometric — {title}",
        f"{bw:.2f} × {bd:.2f} × {bh:.2f} m · {n} room{'s' if n != 1 else ''} · axonometric massing",
    )

    # Back-to-front: draw each room's box, then that room's furniture, then move on.
    for rid, name, r in sorted(room_specs, key=lambda t: t[2].x0 + t[2].z0):
        H = r.y1
        f00, fL0, fLW, f0W = sp(r.x0, 0, r.z0), sp(r.x1, 0, r.z0), sp(r.x1, 0, r.z1), sp(r.x0, 0, r.z1)
        seg.append(f'<polygon points="{f00[0]:.1f},{f00[1]:.1f} {fL0[0]:.1f},{fL0[1]:.1f} {fLW[0]:.1f},{fLW[1]:.1f} {f0W[0]:.1f},{f0W[1]:.1f}" fill="#f3e9d8" fill-opacity="0.92" stroke="{_INK}" stroke-width="1.6"/>')
        for (bx, bz) in ((r.x0, r.z0), (r.x1, r.z0), (r.x0, r.z1)):
            b, t = sp(bx, 0, bz), sp(bx, H, bz)
            seg.append(f'<line x1="{b[0]:.1f}" y1="{b[1]:.1f}" x2="{t[0]:.1f}" y2="{t[1]:.1f}" stroke="{_INK_SOFT}" stroke-width="1.3"/>')
        c00, cL0, c0W = sp(r.x0, H, r.z0), sp(r.x1, H, r.z0), sp(r.x0, H, r.z1)
        seg.append(f'<polyline points="{cL0[0]:.1f},{cL0[1]:.1f} {c00[0]:.1f},{c00[1]:.1f} {c0W[0]:.1f},{c0W[1]:.1f}" fill="none" stroke="{_INK_SOFT}" stroke-width="1.2" stroke-dasharray="4 3"/>')
        nl = sp((r.x0 + r.x1) / 2, H, (r.z0 + r.z1) / 2)
        seg.append(f'<text x="{nl[0]:.1f}" y="{nl[1]-4:.1f}" text-anchor="middle" fill="{_INK}" font-size="11" font-weight="700">{escape(name[:18])}</text>')

        for o in sorted(by_room.get(rid, []), key=_obj_centre_sum):
            _iso_draw_object(seg, sp, o, r)

    # Orphans (centre in no room) are usually edge openings whose centre lands on
    # a wall line — clamp them to the building envelope so they read as on-wall
    # rather than hanging off the floor. Drawn last so they still stay visible;
    # the count is logged above for anyone auditing placement.
    for o in sorted(orphans, key=_obj_centre_sum):
        _iso_draw_object(seg, sp, o, bb)

    seg.append("</svg>")
    total_objs = len([o for o in (graph.get("objects") or []) if isinstance(o, dict)])
    placements = [
        {"id": o.get("id"), "role": o.get("role") or "furniture",
         "mode": "orphan" if o in orphans else "massing"}
        for o in depictable
    ]
    return {
        "drawing_type": "isometric_view",
        "preview_svg": "".join(seg),
        "placements": placements,
        "summary": {
            "length_m": round(bw, 2), "width_m": round(bd, 2), "height_m": round(bh, 2),
            "rooms": n, "objects": total_objs, "orphans": len(orphans),
        },
    }


def _obj_centre_sum(o: dict) -> float:
    """Painter-order key for furniture: farther pieces (smaller x+z centre) first."""
    r = object_rect(o)
    return (r.x0 + r.x1 + r.z0 + r.z1) / 2.0


def _iso_draw_object(seg: list[str], sp, o: dict, room: Rect | None = None) -> None:
    """Draw one object as a shaded axonometric box (three visible faces) at its
    world position, coloured by role: windows glazed, doors timber, else furniture.
    When ``room`` is given the box is clamped into that room's envelope so a piece
    is never drawn hanging off the floor or punched through a wall."""
    r = object_rect(o)
    if room is not None:
        r = _clamp_rect(r, room)
    x0, x1, z0, z1, h = r.x0, r.x1, r.z0, r.z1, r.y1
    role = str(o.get("role") or "").lower()
    fill = _OPENING if role == "window" else _DOOR if role == "door" else _FILL
    top = [sp(x0, h, z0), sp(x1, h, z0), sp(x1, h, z1), sp(x0, h, z1)]
    left = [sp(x1, 0, z0), sp(x1, h, z0), sp(x1, h, z1), sp(x1, 0, z1)]
    front = [sp(x0, 0, z1), sp(x1, 0, z1), sp(x1, h, z1), sp(x0, h, z1)]
    for face, shade in ((front, 0.85), (left, 0.7), (top, 1.0)):
        pts = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in face)
        seg.append(f'<polygon points="{pts}" fill="{fill}" fill-opacity="{shade*0.7:.2f}" stroke="{_POCHE}" stroke-width="1.3"/>')
    lbl = sp((x0 + x1) / 2, h, (z0 + z1) / 2)
    seg.append(f'<text x="{lbl[0]:.1f}" y="{lbl[1]-4:.1f}" text-anchor="middle" fill="#2c221a" font-size="9">{_label(str(o.get("name") or o.get("type") or "item"))[:14]}</text>')


# ── Detail sheet ─────────────────────────────────────────────────────────────


def generate_detail_package(graph: dict) -> dict:
    """Architectural junction callouts for one chosen room + its materials.

    A detail is a close-up of one junction, so this deterministically picks a
    subject — the room with the largest footprint — and names it in the title
    block, then draws its four standard interior construction details (wall/
    floor, wall/ceiling, window jamb, door threshold) annotated with the
    design's own material palette. Always renders (single- or multi-room);
    never claims to show more than the one room it chose.
    """
    subject_name = _largest_room_name(graph) or _label(_room_type(graph))
    materials = [
        str(m.get("name")).strip()
        for m in (graph.get("materials") or [])
        if isinstance(m, dict) and m.get("name")
    ]
    roles = {str(o.get("role") or "") for o in _objects(graph)}
    floor_mat = materials[0] if materials else "screed + finish"
    wall_mat = materials[1] if len(materials) > 1 else "plaster + paint"
    ceil_mat = materials[2] if len(materials) > 2 else "gypsum board"

    details = [
        ("D1 · Wall / Floor", f"Skirting junction · floor: {floor_mat}", "floor"),
        ("D2 · Wall / Ceiling", f"Cornice junction · ceiling: {ceil_mat}", "ceiling"),
        ("D3 · Window Jamb", f"Reveal + sill · glazing line" if "window" in roles else "Typical reveal + sill", "window"),
        ("D4 · Door Threshold", f"Frame + floor transition" if "door" in roles else "Typical frame + transition", "door"),
    ]

    seg = _svg_open(
        f"Detail Sheet — {_label(subject_name)}",
        f"Junctions for the largest room ({_label(subject_name)}) · wall finish: {wall_mat}",
    )
    cell_w = (CW - PAD * 2 - 30) / 2
    cell_h = (CH - PAD - 80 - 30) / 2
    x0, y0 = PAD, 80
    for i, (title, note, kind) in enumerate(details):
        cx = x0 + (i % 2) * (cell_w + 30)
        cy = y0 + (i // 2) * (cell_h + 30)
        seg.append(f'<rect x="{cx:.1f}" y="{cy:.1f}" width="{cell_w:.1f}" height="{cell_h:.1f}" rx="10" fill="#fbf4e8" stroke="{_INK_SOFT}" stroke-width="1.4"/>')
        seg.append(f'<text x="{cx+14:.1f}" y="{cy+24:.1f}" fill="{_INK}" font-size="13" font-weight="700">{escape(title)}</text>')
        seg.append(f'<text x="{cx+14:.1f}" y="{cy+44:.1f}" fill="{_INK_SOFT}" font-size="11">{escape(note)}</text>')
        seg.extend(_detail_schematic(cx, cy, cell_w, cell_h, kind))
    seg.append("</svg>")

    return {
        "drawing_type": "detail_sheet",
        "preview_svg": "".join(seg),
        "summary": {
            "detail_count": len(details),
            "materials_cited": materials[:3],
            "subject_room": subject_name,
            "subject": "wall/floor junction",
        },
    }


def _largest_room_name(graph: dict) -> str | None:
    """Name of the placed room with the largest footprint (the detail subject)."""
    rooms = layout_rooms(graph)
    if not rooms:
        return None
    idx = max(
        range(len(rooms)),
        key=lambda i: (lambda r: (r.x1 - r.x0) * (r.z1 - r.z0))(room_rect(rooms[i])),
    )
    return room_name(rooms[idx], idx)


def _detail_schematic(cx: float, cy: float, cw: float, ch: float, kind: str) -> list[str]:
    """A small, schematic junction drawing inside a detail cell."""
    bx, by = cx + 24, cy + 64
    bw, bh = cw - 48, ch - 88
    out: list[str] = []
    if kind == "floor":
        out.append(f'<rect x="{bx:.1f}" y="{by+bh*0.55:.1f}" width="{bw:.1f}" height="{bh*0.45:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')  # floor slab
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw*0.16:.1f}" height="{bh*0.55:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')  # wall
        out.append(f'<rect x="{bx:.1f}" y="{by+bh*0.42:.1f}" width="{bw*0.22:.1f}" height="{bh*0.13:.1f}" fill="{_FILL}" stroke="{_POCHE}" stroke-width="1.2"/>')  # skirting
    elif kind == "ceiling":
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw:.1f}" height="{bh*0.22:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')  # ceiling slab
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw*0.16:.1f}" height="{bh:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')  # wall
        out.append(f'<rect x="{bx:.1f}" y="{by+bh*0.22:.1f}" width="{bw*0.2:.1f}" height="{bh*0.12:.1f}" fill="{_FILL}" stroke="{_POCHE}" stroke-width="1.2"/>')  # cornice
    elif kind == "window":
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw*0.18:.1f}" height="{bh:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')  # left jamb
        out.append(f'<rect x="{bx+bw*0.82:.1f}" y="{by:.1f}" width="{bw*0.18:.1f}" height="{bh:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')  # right jamb
        out.append(f'<line x1="{bx+bw*0.18:.1f}" y1="{by+bh*0.5:.1f}" x2="{bx+bw*0.82:.1f}" y2="{by+bh*0.5:.1f}" stroke="{_OPENING}" stroke-width="3"/>')  # glazing
    else:  # door
        out.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw*0.16:.1f}" height="{bh:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')  # jamb
        out.append(f'<rect x="{bx+bw*0.16:.1f}" y="{by:.1f}" width="{bw*0.08:.1f}" height="{bh:.1f}" fill="{_DOOR}" fill-opacity="0.5" stroke="{_POCHE}" stroke-width="1.2"/>')  # frame
        out.append(f'<line x1="{bx:.1f}" y1="{by+bh:.1f}" x2="{bx+bw:.1f}" y2="{by+bh:.1f}" stroke="{_INK}" stroke-width="2"/>')  # threshold/floor
    return out
