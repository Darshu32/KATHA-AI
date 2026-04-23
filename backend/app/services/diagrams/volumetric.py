"""Volumetric diagram (BRD Layer 2B #4).

Axonometric (iso-style) view of the room as a 3D block with each object
rendered as a wireframe volume. Voids between objects are highlighted
with a lighter hatch so the spatial reading is clear at a glance.
"""

from __future__ import annotations

from app.services.diagrams.svg_base import (
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    background,
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)

# Axonometric projection: 30° / 30° tilt.
COS30 = 0.8660
SIN30 = 0.5


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _project(x: float, y: float, z: float, scale: float, ox: float, oy: float) -> tuple[float, float]:
    """World (x,y up,z) -> iso screen coords. y is metres up, z is plan depth."""
    px = ox + (x - z) * COS30 * scale
    py = oy + ((x + z) * SIN30 - y) * scale
    return px, py


def _box(x: float, y: float, z: float, l: float, w: float, h: float, scale: float, ox: float, oy: float, fill: str, stroke_w: float = 0.8) -> str:
    """Draw an axonometric wireframe box for a world-space AABB."""
    # 8 corners
    corners = [
        _project(x, y, z, scale, ox, oy),
        _project(x + l, y, z, scale, ox, oy),
        _project(x + l, y, z + w, scale, ox, oy),
        _project(x, y, z + w, scale, ox, oy),
        _project(x, y + h, z, scale, ox, oy),
        _project(x + l, y + h, z, scale, ox, oy),
        _project(x + l, y + h, z + w, scale, ox, oy),
        _project(x, y + h, z + w, scale, ox, oy),
    ]
    # Fills: top + 2 sides.
    top = f'<polygon points="{_poly(corners[4], corners[5], corners[6], corners[7])}" fill="{fill}" fill-opacity="0.55" stroke="{INK}" stroke-width="{stroke_w}"/>'
    right = f'<polygon points="{_poly(corners[1], corners[5], corners[6], corners[2])}" fill="{fill}" fill-opacity="0.75" stroke="{INK}" stroke-width="{stroke_w}"/>'
    front = f'<polygon points="{_poly(corners[3], corners[2], corners[6], corners[7])}" fill="{fill}" fill-opacity="0.90" stroke="{INK}" stroke-width="{stroke_w}"/>'
    return top + right + front


def _poly(*pts) -> str:
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def generate(graph: dict, *, canvas_w: int = 960, canvas_h: int = 560) -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 5.0)
    room_h = float(dims.get("height") or 3.0)

    # Scale so projected room spans the canvas roughly.
    projected_width_units = (room_l + room_w) * COS30
    projected_height_units = (room_l + room_w) * SIN30 + room_h
    scale = min((canvas_w - 120) / projected_width_units, (canvas_h - 160) / projected_height_units)

    ox = canvas_w / 2
    oy = canvas_h - 80

    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(title_block(40, 36, "Volumetric", f"Axonometric view — {room_l:.1f} x {room_w:.1f} x {room_h:.1f} m", width=canvas_w - 80))

    # Room wireframe (ground rectangle + back walls).
    g_a = _project(0, 0, 0, scale, ox, oy)
    g_b = _project(room_l, 0, 0, scale, ox, oy)
    g_c = _project(room_l, 0, room_w, scale, ox, oy)
    g_d = _project(0, 0, room_w, scale, ox, oy)
    body.append(f'<polygon points="{_poly(g_a, g_b, g_c, g_d)}" fill="{PAPER_DEEP}" stroke="{INK_SOFT}" stroke-width="0.8"/>')
    # Back walls as dashed.
    top_a = _project(0, room_h, 0, scale, ox, oy)
    top_b = _project(room_l, room_h, 0, scale, ox, oy)
    top_c = _project(room_l, room_h, room_w, scale, ox, oy)
    top_d = _project(0, room_h, room_w, scale, ox, oy)
    for a, b in [(g_a, top_a), (g_b, top_b), (g_c, top_c), (g_d, top_d), (top_a, top_b), (top_b, top_c), (top_c, top_d), (top_d, top_a)]:
        body.append(line(a[0], a[1], b[0], b[1], stroke=INK_MUTED, stroke_width=0.5, dash="2 3"))

    # Void hatch: light diagonal pattern on floor.
    defs = (
        '<defs><pattern id="voidHatch" patternUnits="userSpaceOnUse" width="10" height="10">'
        f'<path d="M 0 10 L 10 0" stroke="{INK_MUTED}" stroke-width="0.5" opacity="0.35"/></pattern></defs>'
    )
    body.append(defs)
    body.append(f'<polygon points="{_poly(g_a, g_b, g_c, g_d)}" fill="url(#voidHatch)" opacity="0.6"/>')

    # Sort objects back-to-front (larger x+z first → drawn earlier).
    objs = list(graph.get("objects", []))
    objs.sort(key=lambda o: -(float((o.get("position") or {}).get("x", 0)) + float((o.get("position") or {}).get("z", 0))))

    palette = ["#b79a74", "#8a6a3b", "#5a4632", "#c9b79a", "#d7c3a6", "#7a4632", "#3a5a4a", "#c98a5a"]
    total_volume = 0.0
    for i, obj in enumerate(objs):
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        x0 = float(pos.get("x", 0)) - (_m(d.get("length")) or 0.4) / 2
        z0 = float(pos.get("z", 0)) - (_m(d.get("width")) or 0.4) / 2
        y0 = float(pos.get("y", 0) or 0)
        l = max(_m(d.get("length")) or 0.4, 0.1)
        w = max(_m(d.get("width")) or 0.4, 0.1)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        total_volume += l * w * h
        body.append(_box(x0, y0, z0, l, w, h, scale, ox, oy, fill=palette[i % len(palette)]))

    # Stats footer.
    room_volume = room_l * room_w * room_h
    void_pct = max(0.0, 100.0 * (room_volume - total_volume) / room_volume) if room_volume else 0
    body.append(text(40, canvas_h - 30, f"Room volume: {room_volume:.1f} m³   |   Object volume: {total_volume:.2f} m³   |   Void: {void_pct:.1f}%", size=10, fill=INK_SOFT))

    svg = svg_open(canvas_w, canvas_h, title="Volumetric") + "".join(body) + svg_close()
    return {
        "id": "volumetric",
        "name": "Volumetric",
        "format": "svg",
        "svg": svg,
        "meta": {"room_volume_m3": room_volume, "object_volume_m3": round(total_volume, 2), "void_pct": round(void_pct, 1)},
    }
