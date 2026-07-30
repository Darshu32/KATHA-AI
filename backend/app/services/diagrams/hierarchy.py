"""Hierarchy diagram (BRD Layer 2B #8).

Three stacked rankings, each read through a single tonal ramp (darkest =
dominant) so rank is legible without colour:
  1. Visual     — objects ranked by volume.
  2. Material   — palette share by footprint area.
  3. Functional — primary vs secondary vs storage vs accent.

Rows sit in the left region so the LLM authoring overlay composes on top.
"""

from __future__ import annotations

from app.services.diagrams.svg_base import (
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    WHITE,
    background,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
    tone,
)

FUNCTIONAL_BUCKETS: dict[str, list[str]] = {
    "primary use": ["sofa", "bed", "dining_table", "desk", "conference_table", "island", "kitchen_island"],
    "secondary use": ["chair", "dining_chair", "lounge_chair", "office_chair", "coffee_table", "side_table", "console_table"],
    "storage": ["bookshelf", "wardrobe", "cabinet", "tv_unit", "media_console", "cabinetry"],
    "accent": ["rug", "plant", "wall_art", "floor_lamp", "lamp", "sculpture", "pendant"],
}

ROW_W = 610  # left region, clears the overlay rail


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _vol(obj: dict) -> float:
    d = obj.get("dimensions") or {}
    return _m(d.get("length")) * _m(d.get("width")) * max(_m(d.get("height")), 0.05)


def _functional_bucket(obj_type: str) -> str:
    t = (obj_type or "").lower()
    for bucket, types in FUNCTIONAL_BUCKETS.items():
        if t in types:
            return bucket
    return "accent"


def generate(graph: dict, *, canvas_w: int = 900, canvas_h: int = 560) -> dict:
    body: list[str] = [background(canvas_w, canvas_h, fill=PAPER)]
    body.append(title_block(40, 36, "Hierarchy", "Visual (size) · Material (share) · Functional (role)", width=canvas_w - 80))

    row_h = 116
    row_y = 100
    body.append(_visual_row(graph, 40, row_y, ROW_W, row_h))
    body.append(_share_row(_material_shares(graph), "MATERIAL HIERARCHY", 40, row_y + row_h + 34, ROW_W))
    body.append(_share_row(_functional_shares(graph), "FUNCTIONAL HIERARCHY", 40, row_y + 2 * row_h + 68, ROW_W))

    svg = svg_open(canvas_w, canvas_h, title="Hierarchy") + "".join(body) + svg_close()
    return {"id": "hierarchy", "name": "Hierarchy", "format": "svg", "svg": svg, "meta": {"object_count": len(graph.get("objects", []))}}


def _visual_row(graph: dict, x: float, y: float, w: float, h: float) -> str:
    objs = sorted(graph.get("objects", []), key=_vol, reverse=True)[:6]
    parts = [text(x, y - 4, "VISUAL HIERARCHY", size=9, weight="600", fill=INK_SOFT)]
    if not objs:
        parts.append(text(x, y + h / 2, "(no objects)", size=11, fill=INK_MUTED))
        return "".join(parts)
    max_v = _vol(objs[0]) or 1.0
    n = len(objs)
    gap = 12
    bw = (w - gap * (n - 1)) / n
    base_y = y + h
    for i, obj in enumerate(objs):
        ratio = _vol(obj) / max_v
        bh = h * (0.28 + 0.62 * ratio)
        bx = x + i * (bw + gap)
        parts.append(rect(bx, base_y - bh, bw, bh, fill=tone(i, n), stroke=WHITE, stroke_width=0.8))
        parts.append(text(bx + bw / 2, base_y - bh - 5, f"{_vol(obj):.2f} m³", size=8, fill=INK_MUTED, anchor="middle"))
        parts.append(text(bx + bw / 2, base_y + 13, (obj.get("type") or "?").replace("_", " "), size=8.5, fill=INK_SOFT, anchor="middle"))
        parts.append(text(bx + 3, base_y - bh + 12, f"{i + 1}", size=9, weight="600", fill=WHITE))
    return "".join(parts)


def _material_shares(graph: dict) -> list[tuple[str, float]]:
    shares: dict[str, float] = {}
    for obj in graph.get("objects", []):
        mat = (obj.get("material") or "unassigned").split("_")[0].title() or "Unassigned"
        d = obj.get("dimensions") or {}
        shares[mat] = shares.get(mat, 0.0) + (_m(d.get("length")) * _m(d.get("width")) or 0.3)
    return sorted(shares.items(), key=lambda s: -s[1])


def _functional_shares(graph: dict) -> list[tuple[str, float]]:
    counts: dict[str, float] = {}
    for obj in graph.get("objects", []):
        b = _functional_bucket(obj.get("type"))
        counts[b] = counts.get(b, 0) + 1
    order = ["primary use", "secondary use", "storage", "accent"]
    return [(b, counts.get(b, 0)) for b in order if counts.get(b, 0) > 0]


def _share_row(shares: list[tuple[str, float]], label: str, x: float, y: float, w: float) -> str:
    parts = [text(x, y - 4, label, size=9, weight="600", fill=INK_SOFT)]
    total = sum(v for _, v in shares) or 1.0
    n = len(shares) or 1
    bar_y = y + 40
    bar_h = 34
    cur = x
    for i, (name, val) in enumerate(shares):
        seg = w * (val / total)
        parts.append(rect(cur, bar_y, seg, bar_h, fill=tone(i, n), stroke=WHITE, stroke_width=0.8))
        pct = 100 * val / total
        if seg > 54:
            fill = WHITE if i < n / 2 else INK
            parts.append(text(cur + seg / 2, bar_y + bar_h / 2 + 4, f"{name}  {pct:.0f}%", size=9.5, fill=fill, anchor="middle"))
        cur += seg
    # Rank caption under the bar.
    caption = "  ›  ".join(name for name, _ in shares[:4])
    parts.append(text(x, bar_y + bar_h + 18, caption, size=8.5, fill=INK_MUTED))
    return "".join(parts)
