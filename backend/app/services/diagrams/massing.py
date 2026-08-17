"""Massing diagram (BRD Layer 2B #3) — horizontal + vertical.

Two stark panels. Horizontal massing: top-down footprint of the WHOLE plan
(room outlines + each mass toned by its volume rank, heavier = darker) so weight
distribution reads at a glance. Vertical massing: side silhouette against the
plan height with a clean height-band allocation bar. On-brand figure-ground
register — no opacity fades. Content sits in the left region so the LLM
authoring overlay (top band + right rail) composes without collision. Frames
the full plan via the shared plan_geom helper, so multi-room designs place every
room's furniture at its true position rather than cramming it into room 1.
"""

from __future__ import annotations

from app.services.diagrams.plan_geom import plan_bounds
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


def generate(graph: dict, *, canvas_w: int = 1000, canvas_h: int = 520) -> dict:
    pb = plan_bounds(graph)
    foot_l, foot_w, foot_h = pb["l"], pb["w"], pb["h"]
    min_x, min_z = pb["min_x"], pb["min_z"]
    # Objects + room outlines pre-shifted into footprint space (min corner → 0).
    objects = [
        {**o, "x": o["x"] - min_x, "z": o["z"] - min_z}
        for o in pb["objects"]
    ]
    spaces = [
        {**s, "x": s["x"] - min_x, "z": s["z"] - min_z}
        for s in pb["spaces"]
    ]

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(
        title_block(
            40, 36, "Massing",
            f"{foot_l:.1f} x {foot_w:.1f} x {foot_h:.1f} m   ·   horizontal · vertical · weight",
            width=canvas_w - 80,
        )
    )

    # Two panels kept within the left region (x < ~740).
    top = 128
    p_h = canvas_h - top - 40
    body.append(text(40, top - 8, "HORIZONTAL", size=9, weight="600", fill=INK_SOFT))
    body.append(text(390, top - 8, "VERTICAL", size=9, weight="600", fill=INK_SOFT))
    body.append(_horizontal_panel(objects, spaces, foot_l, foot_w, 40, top, 320, p_h))
    body.append(_vertical_panel(objects, foot_l, foot_h, 384, top, 356, p_h))

    svg = svg_open(canvas_w, canvas_h, title="Massing") + "".join(body) + svg_close()
    return {
        "id": "massing",
        "name": "Massing",
        "format": "svg",
        "svg": svg,
        "meta": {
            "plan_m": {"length": round(foot_l, 2), "width": round(foot_w, 2), "height": round(foot_h, 2)},
            "object_count": len(objects),
            "room_count": len(spaces),
        },
    }


def _panel_transform(room_l, room_w, x0, y0, pw, ph, margin):
    avail_w = pw - 2 * margin
    avail_h = ph - 2 * margin
    scale = min(avail_w / room_l, avail_h / room_w)
    plan_w = room_l * scale
    plan_h = room_w * scale
    return scale, x0 + (pw - plan_w) / 2, y0 + (ph - plan_h) / 2


def _horizontal_panel(objects, spaces, foot_l, foot_w, x0, y0, pw, ph):
    scale, tx, ty = _panel_transform(foot_l, foot_w, x0, y0, pw, ph, margin=24)
    parts: list[str] = [rect(tx, ty, foot_l * scale, foot_w * scale, fill=WHITE, stroke=INK, stroke_width=1.4)]
    # Room divisions — thin outlines so a multi-room plan reads as its rooms.
    for s in spaces:
        if s["l"] <= 0 or s["w"] <= 0:
            continue
        parts.append(rect(
            tx + s["x"] * scale, ty + s["z"] * scale, s["l"] * scale, s["w"] * scale,
            fill="none", stroke=INK_MUTED, stroke_width=0.6,
        ))
    ranked = sorted(objects, key=lambda o: o["l"] * o["w"] * o["h"], reverse=True)
    n = len(ranked)
    for rank, obj in enumerate(ranked):
        ow = obj["l"] * scale
        oh = obj["w"] * scale
        px = obj["x"] * scale + tx
        pz = obj["z"] * scale + ty
        # Safety clamp into the plan frame (bounds already contain them).
        px = min(max(px, tx), tx + foot_l * scale - ow)
        pz = min(max(pz, ty), ty + foot_w * scale - oh)
        parts.append(rect(px, pz, ow, oh, fill=tone(rank, n), stroke=WHITE, stroke_width=0.8))
    return "".join(parts)


def _vertical_panel(objects, foot_l, foot_h, x0, y0, pw, ph):
    # Reserve the right 92px of the panel for the height-band bar.
    band_w = 92
    sect_w = pw - band_w
    margin = 24
    avail_w = sect_w - 2 * margin
    avail_h = ph - 2 * margin - 16
    scale = min(avail_w / foot_l, avail_h / foot_h)
    plan_w = foot_l * scale
    plan_h = foot_h * scale
    bx = x0 + (sect_w - plan_w) / 2
    by = y0 + (ph - plan_h) / 2

    parts: list[str] = []
    # Room section frame: floor solid, ceiling dashed, side ticks.
    parts.append(line(bx, by + plan_h, bx + plan_w, by + plan_h, stroke=INK, stroke_width=1.6))
    parts.append(line(bx, by, bx + plan_w, by, stroke=INK_MUTED, stroke_width=0.8, dash="4 4"))
    parts.append(text(bx - 6, by + plan_h + 3, "0", size=8, fill=INK_MUTED, anchor="end"))
    parts.append(text(bx - 6, by + 4, f"{foot_h:.1f}m", size=8, fill=INK_MUTED, anchor="end"))

    # Object silhouettes projected onto the long wall (x vs height), toned by height.
    ranked = sorted(objects, key=lambda o: o["h"], reverse=True)
    n = len(ranked)
    for rank, obj in enumerate(ranked):
        oh = obj["h"]
        ol = obj["l"]
        if oh <= 0:
            continue
        w_px = ol * scale
        h_px = oh * scale
        x_left = bx + obj["x"] * scale
        x_left = min(max(x_left, bx), bx + plan_w - w_px)
        parts.append(rect(x_left, by + plan_h - h_px, w_px, h_px, fill=tone(rank, n), stroke=WHITE, stroke_width=0.7))

    # Height-band allocation bar (BRD bands) — clean tonal stack.
    bands = {"base 0–.5": 0, "body .5–1.2": 0, "upper 1.2–2": 0, "over 2m+": 0}
    keys = list(bands)
    for obj in objects:
        h = obj["h"]
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
