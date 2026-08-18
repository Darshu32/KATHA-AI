"""Volumetric diagram (BRD Layer 2B #4).

Axonometric (iso) read of the whole floor plan as a massing model. Each object
is a solid block with consistent 3-value shading (top light · side mid · front
dark) so the volume reads like a physical study model rather than a wireframe.
The origin is biased left so the LLM authoring overlay's right rail composes
without covering the model. Frames the full plan via the shared plan_geom
helper, so a multi-room design shows every room's furniture inside one envelope.
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
    svg_close,
    svg_open,
    text,
    title_block,
)

COS30 = 0.8660
SIN30 = 0.5

# Consistent 3-value shading — one material, read by face orientation.
FACE_TOP = "#d8d0c0"
FACE_SIDE = "#938c7e"
FACE_FRONT = "#453f38"


def _project(x, y, z, scale, ox, oy):
    return ox + (x - z) * COS30 * scale, oy + ((x + z) * SIN30 - y) * scale


def _poly(*pts):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def _box(x, y, z, l, w, h, scale, ox, oy, stroke_w=0.9):
    c = [
        _project(x, y, z, scale, ox, oy),
        _project(x + l, y, z, scale, ox, oy),
        _project(x + l, y, z + w, scale, ox, oy),
        _project(x, y, z + w, scale, ox, oy),
        _project(x, y + h, z, scale, ox, oy),
        _project(x + l, y + h, z, scale, ox, oy),
        _project(x + l, y + h, z + w, scale, ox, oy),
        _project(x, y + h, z + w, scale, ox, oy),
    ]
    top = f'<polygon points="{_poly(c[4], c[5], c[6], c[7])}" fill="{FACE_TOP}" stroke="{INK}" stroke-width="{stroke_w}"/>'
    side = f'<polygon points="{_poly(c[1], c[5], c[6], c[2])}" fill="{FACE_SIDE}" stroke="{INK}" stroke-width="{stroke_w}"/>'
    front = f'<polygon points="{_poly(c[3], c[2], c[6], c[7])}" fill="{FACE_FRONT}" stroke="{INK}" stroke-width="{stroke_w}"/>'
    return top + side + front


def generate(graph: dict, *, canvas_w: int = 960, canvas_h: int = 560) -> dict:
    # Frame the WHOLE floor plan (shared source of truth), not just the first
    # room — objects carry global coordinates spanning every space.
    pb = plan_bounds(graph)
    min_x, min_z = pb["min_x"], pb["min_z"]
    foot_l, foot_w, foot_h = pb["l"], pb["w"], pb["h"]
    foots, obj_boxes = pb["spaces"], pb["objects"]

    proj_w = (foot_l + foot_w) * COS30
    proj_h = (foot_l + foot_w) * SIN30 + foot_h
    # Fit within the left region (leave ~220px on the right for the overlay).
    fit_w = canvas_w - 260
    scale = min(fit_w / proj_w, (canvas_h - 165) / proj_h)
    ox = 60 + foot_w * COS30 * scale
    # Anchor the back-top corner just below the title; the floor fans down
    # from there so the whole model stays on-canvas.
    oy = 112 + foot_h * scale

    # Everything projects in footprint space (world shifted so the min corner
    # sits at the origin), so a plan that doesn't start at (0,0) still frames.
    def P(x, y, z):
        return _project(x - min_x, y, z - min_z, scale, ox, oy)

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(
        title_block(40, 36, "Volumetric", f"Axonometric massing — {foot_l:.1f} x {foot_w:.1f} x {foot_h:.1f} m", width=canvas_w - 80)
    )

    # Floor plate per room — collectively the plan footprint. Falls back to the
    # overall footprint when the graph carries no spaces (e.g. exterior massing).
    plates = foots or [{"x": min_x, "z": min_z, "l": foot_l, "w": foot_w}]
    for fp in plates:
        fx, fz, fl, fw = fp["x"], fp["z"], fp["l"], fp["w"]
        quad = [P(fx, 0, fz), P(fx + fl, 0, fz), P(fx + fl, 0, fz + fw), P(fx, 0, fz + fw)]
        body.append(f'<polygon points="{_poly(*quad)}" fill="{WHITE}" stroke="{INK_SOFT}" stroke-width="1.0"/>')

    # Back verticals + ceiling ring over the whole footprint — thin, quiet.
    corners = [(0.0, 0.0), (foot_l, 0.0), (foot_l, foot_w), (0.0, foot_w)]
    tops = [_project(cx, foot_h, cz, scale, ox, oy) for cx, cz in corners]
    for (cx, cz), tp in zip(corners, tops):
        gp = _project(cx, 0, cz, scale, ox, oy)
        body.append(line(gp[0], gp[1], tp[0], tp[1], stroke=INK_MUTED, stroke_width=0.5, dash="3 4"))
    for i in range(4):
        a, b = tops[i], tops[(i + 1) % 4]
        body.append(line(a[0], a[1], b[0], b[1], stroke=INK_MUTED, stroke_width=0.5, dash="3 4"))

    # Objects as solid masses, painter's-order back-to-front (shift by min via
    # the x0/z0 passed to _box, which projects them like everything else).
    total_volume = 0.0
    for b in sorted(obj_boxes, key=lambda o: -(o["x"] + o["z"])):
        total_volume += b["l"] * b["w"] * b["h"]
        body.append(_box(b["x"] - min_x, b["y"], b["z"] - min_z, b["l"], b["w"], b["h"], scale, ox, oy))

    room_volume = pb["room_volume"]
    void_pct = max(0.0, 100.0 * (room_volume - total_volume) / room_volume) if room_volume else 0
    # "Room" only reads right when there are rooms; a product/exterior massing
    # has an envelope, not a room.
    vol_label = "Room" if foots else "Envelope"
    body.append(
        text(40, canvas_h - 34, f"{vol_label} {room_volume:.1f} m³   ·   mass {total_volume:.2f} m³   ·   void {void_pct:.0f}%", size=10, fill=INK_SOFT)
    )

    svg = svg_open(canvas_w, canvas_h, title="Volumetric") + "".join(body) + svg_close()
    return {
        "id": "volumetric",
        "name": "Volumetric",
        "format": "svg",
        "svg": svg,
        "meta": {"room_volume_m3": round(room_volume, 2), "object_volume_m3": round(total_volume, 2), "void_pct": round(void_pct, 1)},
    }
