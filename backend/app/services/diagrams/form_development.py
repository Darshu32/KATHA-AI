"""Form Development diagram (BRD Layer 2B #2).

Four-stage evolution as a storyboard — each stage a clean card, arrows
carrying the eye left to right:

  01 Volume      — the raw bounding mass
  02 Grid        — proportional 3x3 division
  03 Subtract    — primary footprints carved out (figure-ground)
  04 Articulate  — theme signature applied

Stark fills, real arrows, quiet captions. Stages inherit the previous.
"""

from __future__ import annotations

from app.knowledge import themes
from app.services.diagrams.svg_base import (
    ACCENT_WARM,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    WHITE,
    arrow,
    background,
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def generate(graph: dict, *, canvas_w: int = 1100, canvas_h: int = 460) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)

    theme_name = (graph.get("style") or {}).get("primary", "")
    pack = themes.get(theme_name) or {}
    signature_moves = pack.get("signature_moves", [])

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(
        title_block(40, 36, "Form Development", f"Evolution in 4 stages · theme: {pack.get('display_name', theme_name or '—')}", width=canvas_w - 80)
    )

    labels = ["01  Volume", "02  Grid", "03  Subtract", "04  Articulate"]
    captions = [
        "Raw bounding volume",
        "3×3 proportional grid",
        "Subtract primary footprints",
        "Apply " + (_signature_short(signature_moves) or "signature"),
    ]

    panel_top = 118
    panel_h = 236
    arrow_gap = 34
    usable = canvas_w - 80 - arrow_gap * 3
    panel_w = usable / 4

    objects = graph.get("objects", [])
    for i in range(4):
        px = 40 + i * (panel_w + arrow_gap)
        body.append(_stage_panel(i, px, panel_top, panel_w, panel_h, room_l, room_w, objects, signature_moves, labels[i]))
        body.append(text(px + panel_w / 2, panel_top + panel_h + 26, captions[i], size=9, fill=INK_SOFT, anchor="middle"))
        if i < 3:
            ay = panel_top + panel_h / 2
            ax = px + panel_w + 6
            body.append(arrow(ax, ay, ax + arrow_gap - 12, ay, stroke=INK_MUTED, stroke_width=1.6, head=7))

    svg = svg_open(canvas_w, canvas_h, title="Form Development") + "".join(body) + svg_close()
    return {
        "id": "form_development",
        "name": "Form Development",
        "format": "svg",
        "svg": svg,
        "meta": {"stages": 4, "signature_moves": signature_moves},
    }


def _stage_panel(stage, x, y, w, h, room_l, room_w, objects, signature_moves, label):
    parts: list[str] = [rect(x, y, w, h, fill=WHITE, stroke=INK_SOFT, stroke_width=0.7, extra='rx="4"')]
    # Number badge.
    parts.append(rect(x, y, 66, 18, fill=INK, stroke="none", extra='rx="0"'))
    parts.append(text(x + 8, y + 13, label, size=9, weight="600", fill=PAPER))

    margin = 22
    avail_w = w - 2 * margin
    avail_h = h - 44
    scale = min(avail_w / room_l, avail_h / room_w)
    rw, rh = room_l * scale, room_w * scale
    rx = x + (w - rw) / 2
    ry = y + 30

    primaries = [
        o for o in objects
        if (o.get("type") or "").lower() in {"sofa", "bed", "dining_table", "desk", "coffee_table", "wardrobe", "bookshelf", "island", "kitchen_island", "cabinetry"}
    ][:6]

    if stage <= 1:
        # Volume: outline (stage 0) then grid (stage 1).
        parts.append(rect(rx, ry, rw, rh, fill=PAPER_DEEP, stroke=INK, stroke_width=1.4))
        if stage >= 1:
            for k in range(1, 3):
                gx = rx + rw * k / 3
                gy = ry + rh * k / 3
                parts.append(line(gx, ry, gx, ry + rh, stroke=INK_MUTED, stroke_width=0.6))
                parts.append(line(rx, gy, rx + rw, gy, stroke=INK_MUTED, stroke_width=0.6))
    else:
        # Subtract / Articulate: mass filled, footprints carved white.
        parts.append(rect(rx, ry, rw, rh, fill=INK, stroke=INK, stroke_width=1.2))
        for obj in primaries:
            d = obj.get("dimensions") or {}
            pos = obj.get("position") or {}
            ow = (_m(d.get("length")) or 0.4) * scale
            oh = (_m(d.get("width")) or 0.3) * scale
            ox = float(pos.get("x", 0)) * scale + rx - ow / 2
            oz = float(pos.get("z", 0)) * scale + ry - oh / 2
            ox = min(max(ox, rx), rx + rw - ow)
            oz = min(max(oz, ry), ry + rh - oh)
            parts.append(rect(ox, oz, ow, oh, fill=WHITE, stroke="none"))
        if stage >= 3:
            # Articulation accent along one edge.
            parts.append(rect(rx, ry, rw, 5, fill=ACCENT_WARM, stroke="none"))

    return "".join(parts)


def _signature_short(moves: list[str]) -> str:
    if not moves:
        return ""
    first = moves[0].lower()
    for key in ("plinth", "pedestal", "taper", "cantilever", "float", "grid", "frame"):
        if key in first:
            return key
    return first.split()[0]
