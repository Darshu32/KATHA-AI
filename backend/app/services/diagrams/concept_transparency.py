"""Concept Transparency diagram (BRD Layer 2B #1).

The core design intent at a glance: objects grouped into functional zones,
each zone drawn as a labelled region enclosing its members. Answers "what is
this design about?" — the parti — rather than just plotting furniture. Flat
fills, clean zone outlines, no opacity mud. Content sits in the left region
so the LLM authoring overlay composes on top.
"""

from __future__ import annotations

from app.knowledge import themes
from app.services.diagrams.svg_base import (
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    WHITE,
    ZONE_COLOURS,
    background,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)

ZONE_RULES: dict[str, list[str]] = {
    "seating": ["sofa", "chair", "dining_chair", "lounge_chair", "office_chair", "armchair"],
    "surface": ["coffee_table", "dining_table", "desk", "console_table", "side_table", "island", "kitchen_island"],
    "rest": ["bed", "single_bed", "queen_bed", "king_bed"],
    "storage": ["bookshelf", "wardrobe", "cabinet", "tv_unit", "media_console", "cabinetry"],
    "circulation": ["rug", "runner"],
    "accent": ["plant", "wall_art", "floor_lamp", "lamp", "sculpture", "pendant", "pendant_light"],
}
_ZONE_KEYS = list(ZONE_RULES)


def _zone_for(obj_type: str) -> str:
    t = (obj_type or "").lower()
    for zone, types in ZONE_RULES.items():
        if t in types:
            return zone
    return "other"


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _zone_colour(zone: str) -> str:
    if zone in ZONE_RULES:
        return ZONE_COLOURS[_ZONE_KEYS.index(zone) % len(ZONE_COLOURS)]
    return "#bfb6a6"


def generate(graph: dict, *, canvas_w: int = 900, canvas_h: int = 600) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)

    theme_name = (graph.get("style") or {}).get("primary", "")
    pack = themes.get(theme_name) or {}
    theme_display = pack.get("display_name", theme_name or "Untitled")

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(
        title_block(40, 36, "Concept Transparency", f"Functional zones · theme: {theme_display}", width=canvas_w - 80)
    )

    # Plan region in the left band (x 40..650, y 120..520).
    x0, y0, pw, ph = 40, 124, 610, 388
    margin = 34
    scale = min((pw - 2 * margin) / room_l, (ph - 2 * margin) / room_w)
    plan_w, plan_h = room_l * scale, room_w * scale
    tx, ty = x0 + (pw - plan_w) / 2, y0 + (ph - plan_h) / 2

    body.append(rect(tx, ty, plan_w, plan_h, fill=WHITE, stroke=INK, stroke_width=1.4))

    # Bucket objects by zone, keep footprint px rects.
    zone_boxes: dict[str, list[tuple[float, float, float, float]]] = {}
    for obj in graph.get("objects", []):
        zone = _zone_for(obj.get("type"))
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        ow = min((_m(d.get("length")) or 0.4) * scale, plan_w)
        oh = min((_m(d.get("width")) or 0.3) * scale, plan_h)
        # Clamp footprints into the room frame so nothing spills off-canvas.
        bx = min(max(float(pos.get("x", 0)) * scale + tx - ow / 2, tx), tx + plan_w - ow)
        bz = min(max(float(pos.get("z", 0)) * scale + ty - oh / 2, ty), ty + plan_h - oh)
        zone_boxes.setdefault(zone, []).append((bx, bz, ow, oh))

    # Zone regions first (behind), then member footprints on top.
    for zone, boxes in zone_boxes.items():
        colour = _zone_colour(zone)
        minx = min(b[0] for b in boxes) - 6
        miny = min(b[1] for b in boxes) - 6
        maxx = max(b[0] + b[2] for b in boxes) + 6
        maxy = max(b[1] + b[3] for b in boxes) + 6
        body.append(
            rect(minx, miny, maxx - minx, maxy - miny, fill="none", stroke=colour, stroke_width=1.3, dash="5 4",
                 extra='rx="6"')
        )
        body.append(text(minx + 2, miny - 4, zone.upper(), size=8, weight="600", fill=colour))
        for bx, byy, bw, bh in boxes:
            body.append(rect(bx, byy, bw, bh, fill=colour, stroke=INK, stroke_width=0.6))

    # Legend (bottom-left, under the plan).
    ly = y0 + ph + 22
    lx = x0
    for zone in zone_boxes:
        body.append(rect(lx, ly - 8, 10, 10, fill=_zone_colour(zone), stroke=INK_SOFT, stroke_width=0.5))
        body.append(text(lx + 15, ly + 1, zone.title(), size=9, fill=INK_SOFT))
        lx += 30 + len(zone) * 6.5

    # Signature caption (quiet).
    signature = pack.get("signature_moves", [])
    if signature:
        body.append(text(x0, ly + 20, "Signature — " + "; ".join(signature[:2]), size=9, fill=INK_MUTED))

    svg = svg_open(canvas_w, canvas_h, title="Concept Transparency") + "".join(body) + svg_close()
    return {
        "id": "concept_transparency",
        "name": "Concept Transparency",
        "format": "svg",
        "svg": svg,
        "meta": {
            "zones": list(zone_boxes),
            "theme": theme_display,
            "object_count": len(graph.get("objects", [])),
        },
    }
