"""Volumetric diagram (BRD Layer 2B #4).

Axonometric (iso) read of the room as a massing model. Each object is a
solid block with consistent 3-value shading (top light · side mid · front
dark) so the volume reads like a physical study model rather than a
wireframe. The origin is biased left so the LLM authoring overlay's right
rail composes without covering the model.
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


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


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
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)
    room_h = float(dims.get("height") or 3.0)

    proj_w = (room_l + room_w) * COS30
    proj_h = (room_l + room_w) * SIN30 + room_h
    # Fit within the left region (leave ~220px on the right for the overlay).
    fit_w = canvas_w - 260
    scale = min(fit_w / proj_w, (canvas_h - 165) / proj_h)
    ox = 60 + room_w * COS30 * scale
    # Anchor the back-top corner just below the title; the floor fans down
    # from there so the whole model stays on-canvas.
    oy = 112 + room_h * scale

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(
        title_block(40, 36, "Volumetric", f"Axonometric massing — {room_l:.1f} x {room_w:.1f} x {room_h:.1f} m", width=canvas_w - 80)
    )

    # Ground plane.
    g = [
        _project(0, 0, 0, scale, ox, oy),
        _project(room_l, 0, 0, scale, ox, oy),
        _project(room_l, 0, room_w, scale, ox, oy),
        _project(0, 0, room_w, scale, ox, oy),
    ]
    body.append(f'<polygon points="{_poly(*g)}" fill="{WHITE}" stroke="{INK_SOFT}" stroke-width="1.0"/>')
    # Back verticals + ceiling ring — thin, quiet, imply the room volume.
    tops = [_project(p[0], room_h, p[1], scale, ox, oy) for p in [(0, 0), (room_l, 0), (room_l, room_w), (0, room_w)]]
    ground3d = [(0, 0), (room_l, 0), (room_l, room_w), (0, room_w)]
    for (gx, gz), tp in zip(ground3d, tops):
        gp = _project(gx, 0, gz, scale, ox, oy)
        body.append(line(gp[0], gp[1], tp[0], tp[1], stroke=INK_MUTED, stroke_width=0.5, dash="3 4"))
    for i in range(4):
        a, b = tops[i], tops[(i + 1) % 4]
        body.append(line(a[0], a[1], b[0], b[1], stroke=INK_MUTED, stroke_width=0.5, dash="3 4"))

    # Objects, painter's-order back-to-front.
    objs = sorted(
        graph.get("objects", []),
        key=lambda o: -(float((o.get("position") or {}).get("x", 0)) + float((o.get("position") or {}).get("z", 0))),
    )
    total_volume = 0.0
    for obj in objs:
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        l = max(_m(d.get("length")) or 0.4, 0.1)
        w = max(_m(d.get("width")) or 0.4, 0.1)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        x0 = float(pos.get("x", 0)) - l / 2
        z0 = float(pos.get("z", 0)) - w / 2
        y0 = float(pos.get("y", 0) or 0)
        total_volume += l * w * h
        body.append(_box(x0, y0, z0, l, w, h, scale, ox, oy))

    room_volume = room_l * room_w * room_h
    void_pct = max(0.0, 100.0 * (room_volume - total_volume) / room_volume) if room_volume else 0
    body.append(
        text(40, canvas_h - 34, f"Room {room_volume:.1f} m³   ·   mass {total_volume:.2f} m³   ·   void {void_pct:.0f}%", size=10, fill=INK_SOFT)
    )

    svg = svg_open(canvas_w, canvas_h, title="Volumetric") + "".join(body) + svg_close()
    return {
        "id": "volumetric",
        "name": "Volumetric",
        "format": "svg",
        "svg": svg,
        "meta": {"room_volume_m3": room_volume, "object_volume_m3": round(total_volume, 2), "void_pct": round(void_pct, 1)},
    }
