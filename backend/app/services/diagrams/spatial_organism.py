"""Spatial Organism diagram (BRD Layer 2B #7).

How a body inhabits the space: a clean plan with human markers at the
interaction points, dashed clearance halos sized to ergonomic circulation
standards, and a solid circulation path from the entry through the primary
anchors. Crisp linework, no opacity mud. Content stays in the left region so
the LLM authoring overlay composes on top.
"""

from __future__ import annotations

from app.knowledge import clearances
from app.services.diagrams.svg_base import (
    ACCENT_COOL,
    ACCENT_WARM,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    WHITE,
    arrow,
    background,
    circle,
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
    "dining_table", "desk", "coffee_table", "wardrobe", "chair", "dining_chair", "office_chair", "island", "kitchen_island",
}


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _human(cx: float, cy: float, r: float = 6, colour: str = INK) -> str:
    return circle(cx, cy - r * 1.2, r * 0.5, fill=colour) + circle(cx, cy, r, fill=colour)


def generate(graph: dict, *, canvas_w: int = 900, canvas_h: int = 620) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)

    # Plan in the left region.
    x0, y0, pw, ph = 40, 124, 610, 400
    margin = 44
    scale = min((pw - 2 * margin) / room_l, (ph - 2 * margin) / room_w)
    rw, rh = room_l * scale, room_w * scale
    rx = x0 + (pw - rw) / 2
    ry = y0 + (ph - rh) / 2

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(title_block(40, 36, "Spatial Organism", "Occupation · circulation · clearance", width=canvas_w - 80))
    body.append(rect(rx, ry, rw, rh, fill=WHITE, stroke=INK, stroke_width=1.4))

    # Entry marker at south wall midpoint.
    entry_cx, entry_cy = rx + rw / 2, ry + rh - 3
    body.append(_human(entry_cx, entry_cy, r=7, colour=ACCENT_WARM))
    body.append(text(entry_cx, entry_cy + 22, "ENTRY", size=9, weight="600", fill=ACCENT_WARM, anchor="middle"))

    anchors: list[tuple[float, float, str]] = []
    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "").lower()
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        ow = min((_m(d.get("length")) or 0.4) * scale, rw)
        oh = min((_m(d.get("width")) or 0.3) * scale, rh)
        # Clamp footprint into the room, then derive centre from the clamp.
        fx = min(max(float(pos.get("x", 0)) * scale + rx - ow / 2, rx), rx + rw - ow)
        fz = min(max(float(pos.get("z", 0)) * scale + ry - oh / 2, ry), ry + rh - oh)
        cx, cz = fx + ow / 2, fz + oh / 2

        halo_m = _CLEARANCE_FOR_TYPE.get(otype)
        if halo_m:
            hp = halo_m * scale
            body.append(
                rect(cx - ow / 2 - hp, cz - oh / 2 - hp, ow + 2 * hp, oh + 2 * hp,
                     fill="none", stroke=ACCENT_COOL, stroke_width=0.9, dash="4 4", extra='rx="4"')
            )
        body.append(rect(cx - ow / 2, cz - oh / 2, ow, oh, fill=PAPER_DEEP, stroke=INK, stroke_width=0.9))
        if ow > 34:
            body.append(text(cx, cz + 3, otype.replace("_", " "), size=8, fill=INK_SOFT, anchor="middle"))
        if otype in _INTERACTION_TYPES:
            body.append(_human(cx, cz + oh / 2 + 13, r=5, colour=INK))
            anchors.append((cx, cz, otype))

    # Circulation path: entry → nearest primaries.
    primaries = [a for a in anchors if a[2] in {"sofa", "bed", "dining_table", "desk", "island", "kitchen_island"}]
    primaries.sort(key=lambda p: (p[0] - entry_cx) ** 2 + (p[1] - entry_cy) ** 2)
    prev = (entry_cx, entry_cy)
    hops = 0
    for px, py, _ in primaries[:4]:
        body.append(arrow(prev[0], prev[1], px, py + 16, stroke=ACCENT_WARM, stroke_width=1.6, head=8, dash="5 3"))
        prev = (px, py)
        hops += 1

    interactions = sum(1 for o in graph.get("objects", []) if (o.get("type") or "").lower() in _INTERACTION_TYPES)
    halo_count = sum(1 for o in graph.get("objects", []) if (o.get("type") or "").lower() in _CLEARANCE_FOR_TYPE)
    body.append(
        text(x0, y0 + ph + 22, f"Interaction points {interactions}   ·   clearance halos {halo_count}   ·   circulation hops {hops}", size=9, fill=INK_SOFT)
    )
    # Legend.
    ly = y0 + ph + 42
    body.append(rect(x0, ly - 8, 10, 10, fill="none", stroke=ACCENT_COOL, stroke_width=0.9, dash="4 4"))
    body.append(text(x0 + 15, ly + 1, "clearance halo", size=9, fill=INK_MUTED))

    svg = svg_open(canvas_w, canvas_h, title="Spatial Organism") + "".join(body) + svg_close()
    return {
        "id": "spatial_organism",
        "name": "Spatial Organism",
        "format": "svg",
        "svg": svg,
        "meta": {"interaction_points": interactions, "clearance_halos": halo_count, "circulation_hops": hops},
    }
