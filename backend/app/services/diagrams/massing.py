"""Massing diagram (BRD Layer 2B #3) — horizontal + vertical.

Two stark panels. Horizontal massing: top-down footprint with each mass
toned by its volume rank (heavier = darker) so weight distribution reads at
a glance. Vertical massing: side section silhouette against the room height,
with a clean height-band allocation bar. On-brand figure-ground register —
no opacity fades. Content sits in the left region so the LLM authoring
overlay (top band + right rail) composes without collision.
"""

from __future__ import annotations

from app.services.diagrams.svg_base import (
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    WHITE,
    background,
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
    tone,
)


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _vol(obj: dict) -> float:
    d = obj.get("dimensions") or {}
    return _m(d.get("length")) * _m(d.get("width")) * max(_m(d.get("height")), 0.05)


def generate(graph: dict, *, canvas_w: int = 1000, canvas_h: int = 520) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)
    room_h = float(dims.get("height") or 3.0)
    objects = list(graph.get("objects", []))

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(
        title_block(
            40, 36, "Massing",
            f"{room_l:.1f} x {room_w:.1f} x {room_h:.1f} m   ·   horizontal · vertical · weight",
            width=canvas_w - 80,
        )
    )

    # Two panels kept within the left region (x < ~740).
    top = 128
    p_h = canvas_h - top - 40
    body.append(text(40, top - 8, "HORIZONTAL", size=9, weight="600", fill=INK_SOFT))
    body.append(text(390, top - 8, "VERTICAL", size=9, weight="600", fill=INK_SOFT))
    body.append(_horizontal_panel(objects, room_l, room_w, 40, top, 320, p_h))
    body.append(_vertical_panel(objects, room_l, room_h, 384, top, 356, p_h))

    svg = svg_open(canvas_w, canvas_h, title="Massing") + "".join(body) + svg_close()
    return {
        "id": "massing",
        "name": "Massing",
        "format": "svg",
        "svg": svg,
        "meta": {
            "room_m": {"length": room_l, "width": room_w, "height": room_h},
            "object_count": len(objects),
        },
    }


def _panel_transform(room_l, room_w, x0, y0, pw, ph, margin):
    avail_w = pw - 2 * margin
    avail_h = ph - 2 * margin
    scale = min(avail_w / room_l, avail_h / room_w)
    plan_w = room_l * scale
    plan_h = room_w * scale
    return scale, x0 + (pw - plan_w) / 2, y0 + (ph - plan_h) / 2


def _horizontal_panel(objects, room_l, room_w, x0, y0, pw, ph):
    scale, tx, ty = _panel_transform(room_l, room_w, x0, y0, pw, ph, margin=24)
    parts: list[str] = [rect(tx, ty, room_l * scale, room_w * scale, fill=WHITE, stroke=INK, stroke_width=1.4)]
    ranked = sorted(objects, key=_vol, reverse=True)
    n = len(ranked)
    for rank, obj in enumerate(ranked):
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        ow = (_m(d.get("length")) or 0.4) * scale
        oh = (_m(d.get("width")) or 0.3) * scale
        px = float(pos.get("x", 0)) * scale + tx - ow / 2
        pz = float(pos.get("z", 0)) * scale + ty - oh / 2
        # Clamp into the room frame.
        px = min(max(px, tx), tx + room_l * scale - ow)
        pz = min(max(pz, ty), ty + room_w * scale - oh)
        parts.append(rect(px, pz, ow, oh, fill=tone(rank, n), stroke=WHITE, stroke_width=0.8))
    return "".join(parts)


def _vertical_panel(objects, room_l, room_h, x0, y0, pw, ph):
    # Reserve the right 92px of the panel for the height-band bar.
    band_w = 92
    sect_w = pw - band_w
    margin = 24
    avail_w = sect_w - 2 * margin
    avail_h = ph - 2 * margin - 16
    scale = min(avail_w / room_l, avail_h / room_h)
    plan_w = room_l * scale
    plan_h = room_h * scale
    bx = x0 + (sect_w - plan_w) / 2
    by = y0 + (ph - plan_h) / 2

    parts: list[str] = []
    # Room section frame: floor solid, ceiling dashed, side ticks.
    parts.append(line(bx, by + plan_h, bx + plan_w, by + plan_h, stroke=INK, stroke_width=1.6))
    parts.append(line(bx, by, bx + plan_w, by, stroke=INK_MUTED, stroke_width=0.8, dash="4 4"))
    parts.append(text(bx - 6, by + plan_h + 3, "0", size=8, fill=INK_MUTED, anchor="end"))
    parts.append(text(bx - 6, by + 4, f"{room_h:.1f}m", size=8, fill=INK_MUTED, anchor="end"))

    # Object silhouettes projected onto the long wall (x vs height), toned by height.
    ranked = sorted(objects, key=lambda o: _m((o.get("dimensions") or {}).get("height")), reverse=True)
    n = len(ranked)
    for rank, obj in enumerate(ranked):
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        oh = _m(d.get("height"))
        ol = _m(d.get("length")) or 0.4
        if oh <= 0:
            continue
        w_px = ol * scale
        h_px = oh * scale
        x_left = bx + (float(pos.get("x", 0)) - ol / 2) * scale
        x_left = min(max(x_left, bx), bx + plan_w - w_px)
        parts.append(rect(x_left, by + plan_h - h_px, w_px, h_px, fill=tone(rank, n), stroke=WHITE, stroke_width=0.7))

    # Height-band allocation bar (BRD bands) — clean tonal stack.
    bands = {"base 0–.5": 0, "body .5–1.2": 0, "upper 1.2–2": 0, "over 2m+": 0}
    keys = list(bands)
    for obj in objects:
        h = _m((obj.get("dimensions") or {}).get("height"))
        i = 0 if h <= 0.5 else 1 if h <= 1.2 else 2 if h <= 2.0 else 3
        bands[keys[i]] += 1
    total = sum(bands.values()) or 1
    bar_x = x0 + sect_w + 8
    bar_top = by
    bar_h = plan_h
    cur = bar_top
    for i, k in enumerate(keys):
        seg = bar_h * (bands[k] / total)
        parts.append(rect(bar_x, cur, 20, seg, fill=tone(i, len(keys)), stroke=WHITE, stroke_width=0.6))
        if seg > 12:
            parts.append(text(bar_x + 26, cur + seg / 2 + 3, f"{k}", size=8, fill=INK_SOFT))
        cur += seg
    return "".join(parts)
