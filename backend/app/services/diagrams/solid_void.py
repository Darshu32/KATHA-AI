"""Solid vs Void diagram (BRD Layer 2B #6).

Plan view that reads positive (solid) vs negative (void) space at a
glance. Solids are filled dark, voids are filled with a light hatch, and
a stat strip at the bottom reports the solid / void ratio + breathing
room (median void cell size).
"""

from __future__ import annotations

from app.services.diagrams.svg_base import (
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    background,
    compute_plan_transform,
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


def _footprints(objects: list[dict]) -> list[tuple[float, float, float, float]]:
    boxes: list[tuple[float, float, float, float]] = []
    for obj in objects:
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        l = _m(d.get("length")) or 0.3
        w = _m(d.get("width")) or 0.3
        x = float(pos.get("x", 0)) - l / 2
        z = float(pos.get("z", 0)) - w / 2
        if l > 0 and w > 0:
            boxes.append((x, z, l, w))
    return boxes


def generate(graph: dict, *, canvas_w: int = 900, canvas_h: int = 620) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)

    scale, tx, ty = compute_plan_transform(room_l, room_w, canvas_w, canvas_h - 80, margin=60)

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(title_block(40, 36, "Solid vs Void", f"Plan analysis — {room_l:.1f} x {room_w:.1f} m", width=canvas_w - 80))

    defs = (
        '<defs>'
        '<pattern id="voidDiag" patternUnits="userSpaceOnUse" width="8" height="8">'
        f'<path d="M 0 8 L 8 0" stroke="{INK_MUTED}" stroke-width="0.5" opacity="0.45"/></pattern>'
        '</defs>'
    )
    body.append(defs)

    # Void field (whole room).
    body.append(rect(tx, ty + 20, room_l * scale, room_w * scale, fill=PAPER_DEEP, stroke=INK, stroke_width=1.2))
    body.append(rect(tx, ty + 20, room_l * scale, room_w * scale, fill="url(#voidDiag)", stroke="none"))

    # Solid footprints.
    boxes = _footprints(graph.get("objects", []))
    total_solid_m2 = 0.0
    for x, z, l, w in boxes:
        sx = x * scale + tx
        sz = z * scale + ty + 20
        sw = l * scale
        sh = w * scale
        body.append(rect(sx, sz, sw, sh, fill=INK, stroke=INK, stroke_width=0.6, opacity=0.85))
        total_solid_m2 += l * w

    room_area = room_l * room_w
    solid_pct = 100 * total_solid_m2 / room_area if room_area else 0
    void_pct = max(0.0, 100.0 - solid_pct)

    # Ratio bar at bottom.
    bar_y = canvas_h - 60
    bar_w = canvas_w - 80
    solid_w = bar_w * solid_pct / 100
    body.append(rect(40, bar_y, solid_w, 22, fill=INK, stroke="none"))
    body.append(rect(40 + solid_w, bar_y, bar_w - solid_w, 22, fill=PAPER_DEEP, stroke=INK_SOFT, stroke_width=0.6))
    body.append(rect(40 + solid_w, bar_y, bar_w - solid_w, 22, fill="url(#voidDiag)", stroke="none"))

    body.append(text(44, bar_y + 15, f"SOLID {solid_pct:.1f}%", size=10, fill=PAPER, weight="600"))
    body.append(text(canvas_w - 44, bar_y + 15, f"VOID {void_pct:.1f}%", size=10, fill=INK_SOFT, weight="600", anchor="end"))

    # Breathing-room metric: mean clearance between items (rough, proxy).
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

    body.append(text(40, bar_y - 12, f"Breathing room (mean inter-object clearance): {breathing:.2f} m", size=10, fill=INK_SOFT))

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
            "room_m2": round(room_area, 2),
            "breathing_m": round(breathing, 2),
        },
    }
