"""Concept Transparency diagram (BRD Layer 2B #1).

Shows the core design intent: functional zones colour-coded by dominant
material, with a short narrative overlay. Answers "what is this design
about?" at a glance.
"""

from __future__ import annotations

from app.knowledge import themes
from app.services.diagrams.svg_base import (
    INK,
    INK_SOFT,
    PAPER,
    ZONE_COLOURS,
    background,
    compute_plan_transform,
    group,
    legend,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)

# Functional zone → which object types fall into it.
ZONE_RULES: dict[str, list[str]] = {
    "seating": ["sofa", "chair", "dining_chair", "lounge_chair", "office_chair", "armchair"],
    "surface": ["coffee_table", "dining_table", "desk", "console_table", "side_table"],
    "rest": ["bed", "single_bed", "queen_bed", "king_bed"],
    "storage": ["bookshelf", "wardrobe", "cabinet", "tv_unit", "media_console"],
    "circulation": ["rug", "runner"],
    "accent": ["plant", "wall_art", "floor_lamp", "lamp", "sculpture"],
}


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


def generate(graph: dict, *, canvas_w: int = 900, canvas_h: int = 600) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)

    theme_name = (graph.get("style") or {}).get("primary", "")
    pack = themes.get(theme_name)
    palette = (pack or {}).get("colour_palette", []) or ZONE_COLOURS

    scale, tx, ty = compute_plan_transform(room_l, room_w, canvas_w, canvas_h, margin=60)

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]

    # Title block.
    theme_display = (pack or {}).get("display_name", theme_name or "Untitled")
    body.append(title_block(40, 40, "Concept Transparency", f"Theme: {theme_display}   |   Room: {room_l:.1f} x {room_w:.1f} m"))

    # Room outline.
    room_px_w = room_l * scale
    room_px_h = room_w * scale
    body.append(rect(tx, ty, room_px_w, room_px_h, fill="none", stroke=INK, stroke_width=1.4))

    # Zone rectangles — one per object, coloured by zone.
    zones_seen: dict[str, str] = {}
    for i, obj in enumerate(graph.get("objects", [])):
        otype = (obj.get("type") or "").lower()
        zone = _zone_for(otype)
        colour = palette[list(ZONE_RULES).index(zone) % len(palette)] if zone in ZONE_RULES else "#bfb6a6"
        zones_seen[zone] = colour

        dims = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        ox = float(pos.get("x", 0)) * scale + tx
        oy = float(pos.get("z", 0)) * scale + ty  # plan: x/z
        ow = _m(dims.get("length")) * scale or 40
        oh = _m(dims.get("width")) * scale or 30
        body.append(rect(ox - ow / 2, oy - oh / 2, ow, oh, fill=colour, stroke=INK_SOFT, stroke_width=0.7, opacity=0.78))
        body.append(text(ox, oy + 3, otype.replace("_", " "), size=9, fill=INK, anchor="middle"))

    # Legend.
    legend_items = [(colour, zone.title()) for zone, colour in zones_seen.items()]
    body.append(legend(40, canvas_h - 40 - 16 * max(len(legend_items), 1), legend_items))

    # Narrative footer.
    signature = (pack or {}).get("signature_moves", [])
    if signature:
        body.append(text(canvas_w - 40, canvas_h - 40, "Signature: " + "; ".join(signature[:2]), size=10, fill=INK_SOFT, anchor="end"))

    svg = svg_open(canvas_w, canvas_h, title="Concept Transparency") + "".join(body) + svg_close()
    return {
        "id": "concept_transparency",
        "name": "Concept Transparency",
        "format": "svg",
        "svg": svg,
        "meta": {
            "zones": list(zones_seen),
            "theme": theme_display,
            "object_count": len(graph.get("objects", [])),
        },
    }
