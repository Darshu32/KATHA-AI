"""Form Development diagram (BRD Layer 2B #2).

Shows a 4-stage evolution from raw volume to final form, with a
proportional grid overlay and per-stage annotations pulled from the
active theme's signature moves.

Stages (applied in order, each inheriting the previous):
  1. Base Volume       — room bounding mass
  2. Proportional Grid — 3x3 golden-ish grid overlay
  3. Subtraction       — primary object footprints carved out
  4. Articulation      — theme signature (plinth / taper / cantilever) tagged
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
    background,
    circle,
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
    body.append(title_block(40, 36, "Form Development", f"Evolution in 4 stages — theme: {pack.get('display_name', theme_name or '—')}", width=canvas_w - 80))

    panel_w = (canvas_w - 80) // 4
    panel_h = canvas_h - 150
    panel_y = 96
    gap = 10

    labels = ["01 Volume", "02 Grid", "03 Subtract", "04 Articulate"]
    for i in range(4):
        px = 40 + i * panel_w
        body.append(_stage_panel(
            stage=i,
            x=px + gap // 2,
            y=panel_y,
            w=panel_w - gap,
            h=panel_h,
            room_l=room_l,
            room_w=room_w,
            objects=graph.get("objects", []),
            signature_moves=signature_moves,
            label=labels[i],
        ))

    # Annotations strip.
    annotations = [
        "Start with the raw bounding volume",
        "Lay 3x3 proportional grid to anchor divisions",
        "Subtract footprints of primary objects",
        "Apply theme signature: " + (signature_moves[0] if signature_moves else "n/a"),
    ]
    for i, ann in enumerate(annotations):
        body.append(text(40 + i * panel_w + panel_w // 2, canvas_h - 30, ann, size=9, fill=INK_SOFT, anchor="middle"))

    svg = svg_open(canvas_w, canvas_h, title="Form Development") + "".join(body) + svg_close()
    return {
        "id": "form_development",
        "name": "Form Development",
        "format": "svg",
        "svg": svg,
        "meta": {"stages": 4, "signature_moves": signature_moves},
    }


def _stage_panel(stage: int, x: float, y: float, w: float, h: float, room_l: float, room_w: float, objects: list, signature_moves: list[str], label: str) -> str:
    parts: list[str] = []
    parts.append(text(x + 6, y + 12, label, size=10, weight="600", fill=INK_SOFT))

    # Panel frame.
    parts.append(rect(x, y + 18, w, h - 18, fill=PAPER_DEEP, stroke=INK_SOFT, stroke_width=0.5))

    # Scale room into panel interior.
    margin = 16
    avail_w = w - 2 * margin
    avail_h = h - 40
    scale = min(avail_w / room_l, avail_h / room_w)
    room_px_w = room_l * scale
    room_px_h = room_w * scale
    rx = x + (w - room_px_w) / 2
    ry = y + 30

    # Stage 1+: volume outline.
    parts.append(rect(rx, ry, room_px_w, room_px_h, fill="none", stroke=INK, stroke_width=1.2))

    # Stage 2+: proportional grid.
    if stage >= 1:
        for i in range(1, 3):
            gx = rx + room_px_w * i / 3
            gy = ry + room_px_h * i / 3
            parts.append(line(gx, ry, gx, ry + room_px_h, stroke=INK_MUTED, stroke_width=0.4, dash="2 3"))
            parts.append(line(rx, gy, rx + room_px_w, gy, stroke=INK_MUTED, stroke_width=0.4, dash="2 3"))

    # Stage 3+: subtract primary objects.
    if stage >= 2:
        primaries = [o for o in objects if (o.get("type") or "").lower() in {"sofa", "bed", "dining_table", "desk", "coffee_table", "wardrobe", "bookshelf"}]
        for obj in primaries[:6]:
            d = obj.get("dimensions") or {}
            pos = obj.get("position") or {}
            ox = float(pos.get("x", 0)) * scale + rx
            oz = float(pos.get("z", 0)) * scale + ry
            ow = (_m(d.get("length")) or 0.4) * scale
            oh = (_m(d.get("width")) or 0.3) * scale
            parts.append(rect(ox - ow / 2, oz - oh / 2, ow, oh, fill=PAPER, stroke=INK_SOFT, stroke_width=0.6, opacity=1.0))

    # Stage 4: articulate with theme signature tag.
    if stage >= 3:
        tag = _signature_short(signature_moves)
        if tag:
            # Small accent mark in corner.
            parts.append(rect(rx - 4, ry + room_px_h - 10, 14, 14, fill=ACCENT_WARM, stroke=INK, stroke_width=0.6))
            parts.append(text(rx + 16, ry + room_px_h, tag, size=9, fill=INK, weight="600"))

    return "".join(parts)


def _signature_short(moves: list[str]) -> str:
    if not moves:
        return ""
    first = moves[0].lower()
    if "plinth" in first or "pedestal" in first:
        return "plinth"
    if "taper" in first or "leg" in first:
        return "taper"
    if "cantilever" in first:
        return "cantilever"
    return first.split()[0]
