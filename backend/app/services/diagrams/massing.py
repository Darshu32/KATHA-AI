"""Massing diagram (BRD Layer 2B #3) — horizontal + vertical.

Horizontal massing: top-down footprint with object blocks sized to volume.
Vertical massing: side section showing silhouette, weight distribution,
and space allocation by height band.
"""

from __future__ import annotations

from app.services.diagrams.svg_base import (
    ACCENT_WARM,
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    background,
    compute_plan_transform,
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


def generate(graph: dict, *, canvas_w: int = 1000, canvas_h: int = 520) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)
    room_h = float(dims.get("height") or 3.0)

    # Split canvas into two panels: left = horizontal plan, right = vertical section.
    panel_w = canvas_w // 2
    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(title_block(40, 36, "Massing", f"{room_l:.1f} x {room_w:.1f} x {room_h:.1f} m   |   horizontal (left)  vertical (right)", width=canvas_w - 80))
    body.append(line(panel_w, 80, panel_w, canvas_h - 40, stroke=INK_SOFT, stroke_width=0.5, dash="3 3"))

    body.append(_horizontal_panel(graph, room_l, room_w, 0, 80, panel_w, canvas_h - 120))
    body.append(_vertical_panel(graph, room_l, room_h, panel_w, 80, panel_w, canvas_h - 120))

    svg = svg_open(canvas_w, canvas_h, title="Massing") + "".join(body) + svg_close()
    return {
        "id": "massing",
        "name": "Massing",
        "format": "svg",
        "svg": svg,
        "meta": {
            "room_m": {"length": room_l, "width": room_w, "height": room_h},
            "object_count": len(graph.get("objects", [])),
        },
    }


def _horizontal_panel(graph: dict, room_l: float, room_w: float, x0: float, y0: float, panel_w: int, panel_h: int) -> str:
    scale, tx, ty = compute_plan_transform(room_l, room_w, panel_w, panel_h, margin=40)
    parts: list[str] = []
    parts.append(text(x0 + 20, y0 + 20, "HORIZONTAL", size=9, weight="600", fill=INK_SOFT))
    parts.append(rect(x0 + tx, y0 + ty, room_l * scale, room_w * scale, fill=PAPER_DEEP, stroke=INK, stroke_width=1.2))

    # Object footprints — opacity scaled by relative volume so heavier pieces read darker.
    max_vol = max((_vol(o) for o in graph.get("objects", [])), default=1.0) or 1.0
    for obj in graph.get("objects", []):
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        px = float(pos.get("x", 0)) * scale + x0 + tx
        pz = float(pos.get("z", 0)) * scale + y0 + ty
        w_px = _m(d.get("length")) * scale or 30
        h_px = _m(d.get("width")) * scale or 20
        opacity = 0.35 + 0.55 * (_vol(obj) / max_vol)
        parts.append(rect(px - w_px / 2, pz - h_px / 2, w_px, h_px, fill=INK_SOFT, stroke=INK, stroke_width=0.6, opacity=opacity))

    return "".join(parts)


def _vertical_panel(graph: dict, room_l: float, room_h: float, x0: float, y0: float, panel_w: int, panel_h: int) -> str:
    margin = 40
    avail_w = panel_w - 2 * margin
    avail_h = panel_h - 2 * margin
    scale = min(avail_w / room_l, avail_h / room_h)
    room_w_px = room_l * scale
    room_h_px = room_h * scale
    bx = x0 + (panel_w - room_w_px) / 2
    by = y0 + (panel_h - room_h_px) / 2

    parts: list[str] = []
    parts.append(text(x0 + 20, y0 + 20, "VERTICAL", size=9, weight="600", fill=INK_SOFT))
    # Floor + ceiling lines.
    parts.append(line(bx, by + room_h_px, bx + room_w_px, by + room_h_px, stroke=INK, stroke_width=1.4))
    parts.append(line(bx, by, bx + room_w_px, by, stroke=INK, stroke_width=0.8, dash="4 4"))
    parts.append(text(bx - 8, by + room_h_px + 4, "0", size=9, fill=INK_MUTED, anchor="end"))
    parts.append(text(bx - 8, by + 4, f"{room_h:.1f}m", size=9, fill=INK_MUTED, anchor="end"))

    # Object silhouettes — projected onto the long wall (x vs height).
    for obj in graph.get("objects", []):
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        px = float(pos.get("x", 0))
        oh = _m(d.get("height"))
        ol = _m(d.get("length")) or 0.4
        if oh <= 0:
            continue
        x_left = bx + (px - ol / 2) * scale
        w_px = ol * scale
        h_px = oh * scale
        y_top = by + room_h_px - h_px
        parts.append(rect(x_left, y_top, w_px, h_px, fill=ACCENT_WARM, stroke=INK, stroke_width=0.6, opacity=0.55))

    # Height-band space allocation bar on the right.
    bar_x = bx + room_w_px + 20
    bar_w = 28
    bands = {"0-0.5m (base)": 0.0, "0.5-1.2m (body)": 0.0, "1.2-2.0m (upper)": 0.0, "2.0m+ (overhead)": 0.0}
    for obj in graph.get("objects", []):
        h = _m((obj.get("dimensions") or {}).get("height"))
        if h <= 0.5:
            bands["0-0.5m (base)"] += h
        elif h <= 1.2:
            bands["0.5-1.2m (body)"] += h
        elif h <= 2.0:
            bands["1.2-2.0m (upper)"] += h
        else:
            bands["2.0m+ (overhead)"] += h
    total = sum(bands.values()) or 1.0
    cursor_y = by
    palette = ["#c9b79a", "#b79a74", "#8a6a3b", "#5a4632"]
    for i, (label, value) in enumerate(bands.items()):
        seg_h = room_h_px * (value / total) if total else 0
        parts.append(rect(bar_x, cursor_y, bar_w, seg_h, fill=palette[i % len(palette)], stroke=INK_SOFT, stroke_width=0.4))
        parts.append(text(bar_x + bar_w + 6, cursor_y + max(seg_h / 2, 8), label, size=8, fill=INK_SOFT))
        cursor_y += seg_h

    return "".join(parts)


def _vol(obj: dict) -> float:
    d = obj.get("dimensions") or {}
    return _m(d.get("length")) * _m(d.get("width")) * max(_m(d.get("height")), 0.05)
