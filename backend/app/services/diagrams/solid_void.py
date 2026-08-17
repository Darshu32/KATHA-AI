"""Solid vs Void diagram (BRD Layer 2B #6) — figure-ground / poché.

Reads positive (solid) vs negative (void) space the way an architect's
figure-ground study does: stark two-tone, no opacity fades. Two panels sit
side by side —

  • SOLID — wall poché + object footprints as black mass on an open (paper)
    floor. The built/occupied mass is the figure.
  • VOID  — the inversion: the open floor becomes the black figure, mass
    drops to white. The *negative* space reads as a shape.

A clean solid/void ratio + a 1 m scale bar sit beneath. The layout keeps to
the left region (x < 650) so the LLM authoring overlay's right rail and top
summary band compose on top without collision. Frames the WHOLE plan via the
shared plan_geom helper, so a multi-room design shows every room (with its
dividing walls) and every object at its true position.
"""

from __future__ import annotations

from app.services.diagrams.plan_geom import plan_bounds
from app.services.diagrams.svg_base import (
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    background,
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)

WHITE = "#ffffff"
WALL_M = 0.12  # synthesised enclosure thickness (m) drawn as poché


def _panel_transform(
    room_l: float, room_w: float, x0: float, y0: float, pw: float, ph: float, margin: float
) -> tuple[float, float, float]:
    """Scale + offset mapping plan metres → px, centred inside a sub-panel."""
    avail_w = pw - 2 * margin
    avail_h = ph - 2 * margin
    scale = min(avail_w / room_l, avail_h / room_w)
    plan_w = room_l * scale
    plan_h = room_w * scale
    tx = x0 + (pw - plan_w) / 2
    ty = y0 + (ph - plan_h) / 2
    return scale, tx, ty


def _figure_ground_panel(
    boxes: list[tuple[float, float, float, float]],
    rooms: list[tuple[float, float, float, float]],
    foot_l: float,
    foot_w: float,
    x0: float,
    y0: float,
    pw: float,
    ph: float,
    *,
    invert: bool,
    label: str,
) -> tuple[str, float]:
    """Draw one figure-ground panel. Returns (svg, scale)."""
    scale, tx, ty = _panel_transform(foot_l, foot_w, x0, y0, pw, ph, margin=30)
    plan_w = foot_l * scale
    plan_h = foot_w * scale
    wt = max(WALL_M * scale, 3.0)  # poché thickness in px, floored so it reads

    # Figure-ground fills. Normal: mass=ink, open=paper. Inverted: open=ink.
    wall_fill = PAPER if invert else INK
    floor_fill = INK if invert else PAPER
    obj_fill = PAPER if invert else INK
    obj_stroke = INK if invert else PAPER

    parts: list[str] = []
    # Panel label sits above the plan.
    parts.append(text(x0 + 6, y0 + 2, label, size=10, weight="600", fill=INK_SOFT))
    # Enclosure poché: outer rect in wall colour, inner floor rect on top.
    parts.append(rect(tx, ty, plan_w, plan_h, fill=wall_fill, stroke=INK, stroke_width=1.0))
    parts.append(
        rect(tx + wt, ty + wt, plan_w - 2 * wt, plan_h - 2 * wt, fill=floor_fill, stroke="none")
    )
    # Room-dividing walls — each room outlined in the wall tone so the
    # multi-room plan reads as its rooms (not one open shell).
    for rx, rz, rl, rw in rooms:
        if rl <= 0 or rw <= 0:
            continue
        parts.append(rect(
            tx + rx * scale, ty + rz * scale, rl * scale, rw * scale,
            fill="none", stroke=wall_fill, stroke_width=max(wt * 0.5, 1.2),
        ))
    # Object footprints — thin contrasting outline keeps neighbours legible.
    for x, z, l, w in boxes:
        sx = tx + max(0.0, x) * scale
        sz = ty + max(0.0, z) * scale
        sw = min(l * scale, tx + plan_w - sx)
        sh = min(w * scale, ty + plan_h - sz)
        if sw <= 0 or sh <= 0:
            continue
        parts.append(rect(sx, sz, sw, sh, fill=obj_fill, stroke=obj_stroke, stroke_width=0.8))
    return "".join(parts), scale


def generate(graph: dict, *, canvas_w: int = 900, canvas_h: int = 620) -> dict:
    pb = plan_bounds(graph)
    foot_l, foot_w = pb["l"], pb["w"]
    min_x, min_z = pb["min_x"], pb["min_z"]
    # Object + room footprints shifted into panel space (min corner → 0).
    boxes = [
        (o["x"] - min_x, o["z"] - min_z, o["l"], o["w"])
        for o in pb["objects"]
        if o["l"] > 0 and o["w"] > 0
    ]
    rooms = [
        (s["x"] - min_x, s["z"] - min_z, s["l"], s["w"])
        for s in pb["spaces"]
    ]

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(
        title_block(
            40, 36, "Solid vs Void",
            f"Figure-ground — {foot_l:.1f} x {foot_w:.1f} m   ·   mass vs open space",
            width=canvas_w - 80,
        )
    )

    # Two panels within the left region (overlay owns x >= 665 / top band).
    panel_y = 128
    panel_h = 300
    gap = 24
    total_w = 610  # 40 .. 650
    panel_w = (total_w - gap) / 2
    solid_svg, scale = _figure_ground_panel(
        boxes, rooms, foot_l, foot_w, 40, panel_y, panel_w, panel_h, invert=False, label="SOLID · mass"
    )
    void_svg, _ = _figure_ground_panel(
        boxes, rooms, foot_l, foot_w, 40 + panel_w + gap, panel_y, panel_w, panel_h, invert=True, label="VOID · open"
    )
    body.append(solid_svg)
    body.append(void_svg)

    # ── Ratios ──────────────────────────────────────────────────────────────
    room_area = foot_l * foot_w
    total_solid_m2 = sum(l * w for _, _, l, w in boxes)
    solid_pct = 100 * total_solid_m2 / room_area if room_area else 0.0
    void_pct = max(0.0, 100.0 - solid_pct)

    # Slim two-tone ratio bar (kept narrow so it clears the overlay rail).
    bar_x, bar_y, bar_w, bar_h = 40, panel_y + panel_h + 34, 560, 20
    solid_w = bar_w * solid_pct / 100
    body.append(rect(bar_x, bar_y, bar_w, bar_h, fill=PAPER, stroke=INK, stroke_width=1.0))
    body.append(rect(bar_x, bar_y, solid_w, bar_h, fill=INK, stroke="none"))
    if solid_w > 46:
        body.append(text(bar_x + 8, bar_y + 14, f"SOLID {solid_pct:.0f}%", size=10, fill=PAPER, weight="600"))
    body.append(
        text(bar_x + bar_w - 8, bar_y + 14, f"VOID {void_pct:.0f}%", size=10, fill=INK, weight="600", anchor="end")
    )

    # Legend + 1 m scale bar sit under the ratio.
    leg_y = bar_y + bar_h + 20
    body.append(rect(bar_x, leg_y - 8, 10, 10, fill=INK, stroke="none"))
    body.append(text(bar_x + 16, leg_y + 1, "mass (walls · objects)", size=9, fill=INK_SOFT))
    body.append(rect(bar_x + 170, leg_y - 8, 10, 10, fill=PAPER, stroke=INK, stroke_width=0.8))
    body.append(text(bar_x + 186, leg_y + 1, "open (void)", size=9, fill=INK_SOFT))

    # 1 m scale bar (right-aligned within the panel band).
    sb_len = max(scale, 12.0)
    sb_x = bar_x + bar_w - sb_len
    sb_y = leg_y
    body.append(line(sb_x, sb_y, sb_x + sb_len, sb_y, stroke=INK, stroke_width=1.4))
    body.append(line(sb_x, sb_y - 3, sb_x, sb_y + 3, stroke=INK, stroke_width=1.4))
    body.append(line(sb_x + sb_len, sb_y - 3, sb_x + sb_len, sb_y + 3, stroke=INK, stroke_width=1.4))
    body.append(text(sb_x + sb_len / 2, sb_y - 6, "1 m", size=8, fill=INK_MUTED, anchor="middle"))

    # Breathing room — mean inter-object clearance (kept, quietly).
    breathing = 0.0
    if len(boxes) >= 2:
        total = 0.0
        pairs = 0
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                dx = max(0, abs((boxes[i][0] + boxes[i][2] / 2) - (boxes[j][0] + boxes[j][2] / 2)) - (boxes[i][2] + boxes[j][2]) / 2)
                dz = max(0, abs((boxes[i][1] + boxes[i][3] / 2) - (boxes[j][1] + boxes[j][3] / 2)) - (boxes[i][3] + boxes[j][3]) / 2)
                total += (dx + dz) / 2
                pairs += 1
        breathing = total / pairs if pairs else 0
    body.append(
        text(bar_x, leg_y + 20, f"Breathing room · mean clearance {breathing:.2f} m", size=9, fill=INK_MUTED)
    )

    svg = svg_open(canvas_w, canvas_h, title="Solid vs Void") + "".join(body) + svg_close()
    return {
        "id": "solid_void",
        "name": "Solid vs Void",
        "format": "svg",
        "svg": svg,
        "meta": {
            "solid_pct": round(solid_pct, 1),
            "void_pct": round(void_pct, 1),
            "solid_m2": round(total_solid_m2, 2),
            "plan_m2": round(room_area, 2),
            "breathing_m": round(breathing, 2),
        },
    }
