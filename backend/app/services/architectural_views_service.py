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

from html import escape
from typing import Any

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

_EDGE_ROLES = {"wall", "window", "door"}


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


def generate_section_package(graph: dict) -> dict:
    """Vertical cut through the room at mid-depth, looking along the depth axis.

    Horizontal axis = room length (x), vertical = height (y). Objects crossing
    the cut plane are poché-filled (cut); the rest are drawn as light elevation
    outlines behind the cut.
    """
    L, W, H = _room(graph)
    objs = [_obj_box(o) for o in _objects(graph)]
    cut_z = W / 2.0

    plot_w, plot_h = CW - PAD * 2, CH - PAD * 2 - 30
    s = min(plot_w / L, plot_h / H)
    ox = PAD + (plot_w - L * s) / 2
    floor_y = PAD + 30 + H * s  # y grows downward in SVG; floor at bottom

    def px(x: float) -> float:
        return ox + x * s

    def py(y: float) -> float:  # world y (height) → screen
        return floor_y - y * s

    seg = _svg_open(
        f"Section A–A — {_label(_room_type(graph))}",
        f"Cut at mid-depth ({cut_z:.2f} m) · ceiling {H:.2f} m · width {L:.2f} m",
    )
    wall_t = max(0.1 * s, 6)

    # Room shell: floor slab, ceiling slab, two wall sections (poché).
    seg.append(f'<rect x="{px(0)-wall_t:.1f}" y="{py(H):.1f}" width="{wall_t:.1f}" height="{H*s:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')
    seg.append(f'<rect x="{px(L):.1f}" y="{py(H):.1f}" width="{wall_t:.1f}" height="{H*s:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')
    seg.append(f'<rect x="{px(0)-wall_t:.1f}" y="{py(H)-wall_t:.1f}" width="{L*s+wall_t*2:.1f}" height="{wall_t:.1f}" fill="url(#poche)" stroke="{_INK}" stroke-width="1.5"/>')
    seg.append(f'<line x1="{px(0):.1f}" y1="{floor_y:.1f}" x2="{px(L):.1f}" y2="{floor_y:.1f}" stroke="{_INK}" stroke-width="3"/>')

    # Objects: cut vs behind.
    cut_items, behind = [], []
    for o in objs:
        if o["role"] == "wall":
            continue
        z0, z1 = o["z"] - o["dz"] / 2, o["z"] + o["dz"] / 2
        (cut_items if z0 <= cut_z <= z1 else behind).append(o)

    for o in sorted(behind, key=lambda b: -b["z"]):
        x = px(o["x"] - o["dx"] / 2)
        w = o["dx"] * s
        h = o["dy"] * s
        seg.append(f'<rect x="{x:.1f}" y="{floor_y-h:.1f}" width="{w:.1f}" height="{h:.1f}" fill="none" stroke="{_INK_SOFT}" stroke-width="1.2" stroke-dasharray="4 3"/>')

    for o in cut_items:
        x = px(o["x"] - o["dx"] / 2)
        w = o["dx"] * s
        h = o["dy"] * s
        fill = _OPENING if o["role"] == "window" else _DOOR if o["role"] == "door" else _FILL
        seg.append(f'<rect x="{x:.1f}" y="{floor_y-h:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" fill="{fill}" stroke="{_POCHE}" stroke-width="2"/>')
        seg.append(f'<text x="{x+w/2:.1f}" y="{floor_y-h-4:.1f}" text-anchor="middle" fill="#2c221a" font-size="10">{_label(o["name"])[:16]}</text>')

    # Dimensions.
    seg.append(_vdim(py(H), floor_y, px(0) - wall_t - 16, f"{H:.2f} m"))
    seg.append(_hdim(px(0), px(L), floor_y + 34, f"{L:.2f} m"))
    seg.append("</svg>")

    placements = (
        [{"id": o["id"], "role": o["role"], "mode": "cut"} for o in cut_items]
        + [{"id": o["id"], "role": o["role"], "mode": "behind"} for o in behind]
    )
    return {
        "drawing_type": "section_view",
        "preview_svg": "".join(seg),
        "placements": placements,
        "summary": {"cut_depth_m": round(cut_z, 2), "ceiling_height_m": round(H, 2), "objects_cut": len(cut_items)},
    }


# ── Elevation view ───────────────────────────────────────────────────────────


def generate_elevation_package(graph: dict) -> dict:
    """Front elevation projected onto the back wall (z=0).

    Horizontal = room length (x), vertical = height (y). Openings on the wall
    are drawn distinctly; furniture silhouettes are layered far-to-near.
    """
    L, W, H = _room(graph)
    objs = [_obj_box(o) for o in _objects(graph)]

    plot_w, plot_h = CW - PAD * 2, CH - PAD * 2 - 30
    s = min(plot_w / L, plot_h / H)
    ox = PAD + (plot_w - L * s) / 2
    floor_y = PAD + 30 + H * s

    def px(x: float) -> float:
        return ox + x * s

    def py(y: float) -> float:
        return floor_y - y * s

    seg = _svg_open(
        f"Elevation — {_label(_room_type(graph))}",
        f"Wall face {L:.2f} m × {H:.2f} m · projected onto rear wall",
    )

    # Wall plane + ground line.
    seg.append(f'<rect x="{px(0):.1f}" y="{py(H):.1f}" width="{L*s:.1f}" height="{H*s:.1f}" fill="#fbf4e8" stroke="{_INK}" stroke-width="2.5"/>')
    seg.append(f'<line x1="{px(0)-20:.1f}" y1="{floor_y:.1f}" x2="{px(L)+20:.1f}" y2="{floor_y:.1f}" stroke="{_INK}" stroke-width="3"/>')

    openings = [o for o in objs if o["role"] in ("window", "door")]
    furniture = [o for o in objs if o["role"] not in _EDGE_ROLES]

    # Furniture silhouettes, far wall first.
    for o in sorted(furniture, key=lambda b: -b["z"]):
        x = px(o["x"] - o["dx"] / 2)
        w = o["dx"] * s
        h = o["dy"] * s
        seg.append(f'<rect x="{x:.1f}" y="{floor_y-h:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" fill="{_FILL}" fill-opacity="0.55" stroke="{_POCHE}" stroke-width="1.6"/>')
        if w > 34:
            seg.append(f'<text x="{x+w/2:.1f}" y="{floor_y-6:.1f}" text-anchor="middle" fill="#2c221a" font-size="10">{_label(o["name"])[:16]}</text>')

    # Openings on the wall.
    for o in openings:
        x = px(o["x"] - o["dx"] / 2)
        w = o["dx"] * s
        h = o["dy"] * s
        sill = o["y"] if o["y"] > 0 else (0.9 if o["role"] == "window" else 0.0)
        top = py(sill + o["dy"])
        oh = o["dy"] * s
        fill = _OPENING if o["role"] == "window" else _DOOR
        seg.append(f'<rect x="{x:.1f}" y="{top:.1f}" width="{w:.1f}" height="{oh:.1f}" fill="{fill}" fill-opacity="0.4" stroke="{_INK}" stroke-width="1.8"/>')
        seg.append(f'<text x="{x+w/2:.1f}" y="{top-4:.1f}" text-anchor="middle" fill="#2c221a" font-size="10">{_label(o["role"])}</text>')

    seg.append(_vdim(py(H), floor_y, px(0) - 16, f"{H:.2f} m"))
    seg.append(_hdim(px(0), px(L), floor_y + 34, f"{L:.2f} m"))
    seg.append("</svg>")

    placements = (
        [{"id": o["id"], "role": o["role"], "mode": "opening"} for o in openings]
        + [{"id": o["id"], "role": o["role"], "mode": "silhouette"} for o in furniture]
    )
    return {
        "drawing_type": "elevation_view",
        "preview_svg": "".join(seg),
        "placements": placements,
        "summary": {"wall_length_m": round(L, 2), "wall_height_m": round(H, 2), "openings": len(openings)},
    }


# ── Isometric view ───────────────────────────────────────────────────────────


_COS30 = 0.8660254
_SIN30 = 0.5


def generate_isometric_package(graph: dict) -> dict:
    """Axonometric massing of the room box + furniture blocks."""
    L, W, H = _room(graph)
    objs = [_obj_box(o) for o in _objects(graph)]

    # Iso projection (metres → screen units, before pixel scale).
    def iso(x: float, y: float, z: float) -> tuple[float, float]:
        return (x - z) * _COS30, (x + z) * _SIN30 - y

    corners = [iso(x, y, z) for x in (0, L) for y in (0, H) for z in (0, W)]
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    span_x = max(xs) - min(xs) or 1
    span_y = max(ys) - min(ys) or 1
    plot_w, plot_h = CW - PAD * 2, CH - PAD * 2 - 30
    s = min(plot_w / span_x, plot_h / span_y)
    ox = PAD + (plot_w - span_x * s) / 2 - min(xs) * s
    oy = PAD + 30 + (plot_h - span_y * s) / 2 - min(ys) * s

    def sp(x: float, y: float, z: float) -> tuple[float, float]:
        ix, iy = iso(x, y, z)
        return ox + ix * s, oy + iy * s

    seg = _svg_open(
        f"Isometric — {_label(_room_type(graph))}",
        f"{L:.2f} × {W:.2f} × {H:.2f} m · axonometric massing",
    )

    # Room floor + back walls (wireframe).
    f00, fL0, fLW, f0W = sp(0, 0, 0), sp(L, 0, 0), sp(L, 0, W), sp(0, 0, W)
    seg.append(f'<polygon points="{f00[0]:.1f},{f00[1]:.1f} {fL0[0]:.1f},{fL0[1]:.1f} {fLW[0]:.1f},{fLW[1]:.1f} {f0W[0]:.1f},{f0W[1]:.1f}" fill="#f3e9d8" stroke="{_INK}" stroke-width="1.6"/>')
    for (bx, bz) in ((0, 0), (L, 0), (0, W)):
        b, t = sp(bx, 0, bz), sp(bx, H, bz)
        seg.append(f'<line x1="{b[0]:.1f}" y1="{b[1]:.1f}" x2="{t[0]:.1f}" y2="{t[1]:.1f}" stroke="{_INK_SOFT}" stroke-width="1.3"/>')
    # Ceiling outline.
    c00, cL0, cLW, c0W = sp(0, H, 0), sp(L, H, 0), sp(L, H, W), sp(0, H, W)
    seg.append(f'<polyline points="{cL0[0]:.1f},{cL0[1]:.1f} {c00[0]:.1f},{c00[1]:.1f} {c0W[0]:.1f},{c0W[1]:.1f}" fill="none" stroke="{_INK_SOFT}" stroke-width="1.2" stroke-dasharray="4 3"/>')

    # Furniture boxes, far (small x+z) first.
    drawn = [o for o in objs if o["role"] != "wall"]
    for o in sorted(drawn, key=lambda b: b["x"] + b["z"]):
        x0, x1 = o["x"] - o["dx"] / 2, o["x"] + o["dx"] / 2
        z0, z1 = o["z"] - o["dz"] / 2, o["z"] + o["dz"] / 2
        h = o["dy"]
        fill = _OPENING if o["role"] == "window" else _DOOR if o["role"] == "door" else _FILL
        # Three visible faces: top, left (x1 side), front (z1 side).
        top = [sp(x0, h, z0), sp(x1, h, z0), sp(x1, h, z1), sp(x0, h, z1)]
        left = [sp(x1, 0, z0), sp(x1, h, z0), sp(x1, h, z1), sp(x1, 0, z1)]
        front = [sp(x0, 0, z1), sp(x1, 0, z1), sp(x1, h, z1), sp(x0, h, z1)]
        for face, shade in ((front, 0.85), (left, 0.7), (top, 1.0)):
            pts = " ".join(f"{p[0]:.1f},{p[1]:.1f}" for p in face)
            seg.append(f'<polygon points="{pts}" fill="{fill}" fill-opacity="{shade*0.7:.2f}" stroke="{_POCHE}" stroke-width="1.3"/>')
        lbl = sp(o["x"], h, o["z"])
        seg.append(f'<text x="{lbl[0]:.1f}" y="{lbl[1]-4:.1f}" text-anchor="middle" fill="#2c221a" font-size="9">{_label(o["name"])[:14]}</text>')

    seg.append("</svg>")
    placements = [{"id": o["id"], "role": o["role"], "mode": "massing"} for o in drawn]
    return {
        "drawing_type": "isometric_view",
        "preview_svg": "".join(seg),
        "placements": placements,
        "summary": {"length_m": round(L, 2), "width_m": round(W, 2), "height_m": round(H, 2), "objects": len(objs)},
    }


# ── Detail sheet ─────────────────────────────────────────────────────────────


def generate_detail_package(graph: dict) -> dict:
    """Architectural junction callouts derived from the room + its materials.

    Four standard interior construction details — wall/floor, wall/ceiling,
    window jamb, door threshold — annotated with the design's own material
    palette. Deterministic; replaces the furniture joinery/hardware sheet.
    """
    L, W, H = _room(graph)
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
        f"Detail Sheet — {_label(_room_type(graph))}",
        f"Key interior junctions · wall finish: {wall_mat}",
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
        "summary": {"detail_count": len(details), "materials_cited": materials[:3]},
    }


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
