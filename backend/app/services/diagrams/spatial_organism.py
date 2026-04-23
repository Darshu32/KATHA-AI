"""Spatial Organism diagram (BRD Layer 2B #7).

Plan view that shows how a human inhabits the space. Adds:
  * human silhouette markers at key interaction points (primary objects)
  * circulation arrows between anchor objects (entry → sofa → table)
  * per-object clearance halos sized to ergonomic circulation standards
"""

from __future__ import annotations

import math

from app.knowledge import clearances
from app.services.diagrams.svg_base import (
    ACCENT_COOL,
    ACCENT_WARM,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    background,
    circle,
    compute_plan_transform,
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)

_CLEARANCE_FOR_TYPE = {
    "bed": clearances.CIRCULATION["around_bed"] / 1000.0,
    "single_bed": clearances.CIRCULATION["around_bed"] / 1000.0,
    "queen_bed": clearances.CIRCULATION["around_bed"] / 1000.0,
    "king_bed": clearances.CIRCULATION["around_bed"] / 1000.0,
    "dining_table": clearances.CIRCULATION["around_dining_table"] / 1000.0,
    "desk": clearances.CIRCULATION["desk_pullout"] / 1000.0,
    "sofa": clearances.CIRCULATION["in_front_of_sofa"] / 1000.0,
    "wardrobe": clearances.CIRCULATION["wardrobe_opening"] / 1000.0,
}

_INTERACTION_TYPES = {
    "sofa", "bed", "single_bed", "queen_bed", "king_bed",
    "dining_table", "desk", "coffee_table", "wardrobe", "chair", "dining_chair", "office_chair",
}


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _human_marker(cx: float, cy: float, r: float = 6, colour: str = INK) -> str:
    head = circle(cx, cy - r * 1.2, r * 0.45, fill=colour)
    body = circle(cx, cy, r, fill=colour, opacity=0.85)
    return head + body


def generate(graph: dict, *, canvas_w: int = 900, canvas_h: int = 620) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)

    scale, tx, ty = compute_plan_transform(room_l, room_w, canvas_w, canvas_h - 80, margin=60)

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(title_block(40, 36, "Spatial Organism", "Human occupation + circulation + clearance halos", width=canvas_w - 80))

    # Room outline.
    rx = tx
    ry = ty + 20
    rw = room_l * scale
    rh = room_w * scale
    body.append(rect(rx, ry, rw, rh, fill=PAPER_DEEP, stroke=INK, stroke_width=1.2))

    # Entry marker (assume midpoint of south wall).
    entry_cx = rx + rw / 2
    entry_cy = ry + rh - 4
    body.append(_human_marker(entry_cx, entry_cy, r=7, colour=ACCENT_WARM))
    body.append(text(entry_cx, entry_cy + 22, "ENTRY", size=9, fill=ACCENT_WARM, weight="600", anchor="middle"))

    anchor_points: list[tuple[float, float, str]] = [(entry_cx, entry_cy, "entry")]

    # Objects + clearance halos + human at interaction points.
    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "").lower()
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        ox = float(pos.get("x", 0)) * scale + rx
        oz = float(pos.get("z", 0)) * scale + ry
        ow = (_m(d.get("length")) or 0.4) * scale
        oh = (_m(d.get("width")) or 0.3) * scale

        # Clearance halo.
        halo_m = _CLEARANCE_FOR_TYPE.get(otype)
        if halo_m:
            halo_px = halo_m * scale
            body.append(rect(ox - ow / 2 - halo_px, oz - oh / 2 - halo_px, ow + 2 * halo_px, oh + 2 * halo_px,
                             fill=ACCENT_COOL, stroke=ACCENT_COOL, stroke_width=0.6, opacity=0.12))

        # Object footprint.
        body.append(rect(ox - ow / 2, oz - oh / 2, ow, oh, fill=INK_SOFT, stroke=INK, stroke_width=0.8, opacity=0.78))
        body.append(text(ox, oz + 3, otype.replace("_", " "), size=9, fill=PAPER, anchor="middle", weight="600"))

        # Human at interaction points.
        if otype in _INTERACTION_TYPES:
            body.append(_human_marker(ox, oz + oh / 2 + 14, r=5.5, colour=INK))
            anchor_points.append((ox, oz, otype))

    # Circulation arrows — connect entry → primary objects in order of distance.
    primaries = [p for p in anchor_points[1:] if p[2] in {"sofa", "bed", "dining_table", "desk"}]
    if primaries:
        primaries.sort(key=lambda p: ((p[0] - entry_cx) ** 2 + (p[1] - entry_cy) ** 2))
        prev = (entry_cx, entry_cy)
        for px, py, _ in primaries[:4]:
            body.append(_arrow(prev[0], prev[1], px, py, colour=ACCENT_WARM))
            prev = (px, py)

    # Stats strip.
    halo_count = sum(1 for o in graph.get("objects", []) if (o.get("type") or "").lower() in _CLEARANCE_FOR_TYPE)
    interactions = sum(1 for o in graph.get("objects", []) if (o.get("type") or "").lower() in _INTERACTION_TYPES)
    body.append(text(40, canvas_h - 40, f"Interaction points: {interactions}   |   Clearance halos: {halo_count}   |   Circulation hops: {max(0, len(primaries[:4]))}", size=10, fill=INK_SOFT))

    svg = svg_open(canvas_w, canvas_h, title="Spatial Organism") + "".join(body) + svg_close()
    return {
        "id": "spatial_organism",
        "name": "Spatial Organism",
        "format": "svg",
        "svg": svg,
        "meta": {"interaction_points": interactions, "clearance_halos": halo_count, "circulation_hops": max(0, len(primaries[:4]))},
    }


def _arrow(x1: float, y1: float, x2: float, y2: float, colour: str = INK) -> str:
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy) or 1.0
    # Shorten so arrow head doesn't bury under the destination marker.
    ux, uy = dx / length, dy / length
    x2s, y2s = x2 - ux * 14, y2 - uy * 14
    shaft = line(x1, y1, x2s, y2s, stroke=colour, stroke_width=1.4, dash="4 3")
    # Triangular head.
    hx, hy = x2s, y2s
    left = (hx - uy * 5, hy + ux * 5)
    right = (hx + uy * 5, hy - ux * 5)
    tip = (hx + ux * 8, hy + uy * 8)
    head = f'<polygon points="{left[0]:.1f},{left[1]:.1f} {right[0]:.1f},{right[1]:.1f} {tip[0]:.1f},{tip[1]:.1f}" fill="{colour}"/>'
    return shaft + head
