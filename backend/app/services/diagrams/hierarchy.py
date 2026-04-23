"""Hierarchy diagram (BRD Layer 2B #8).

Shows three stacked hierarchies:
  1. Visual  — objects ranked by volume, largest = dominant.
  2. Material — palette share by material footprint area.
  3. Functional — primary purpose vs secondary vs storage / accent.
"""

from __future__ import annotations

from app.services.diagrams.svg_base import (
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    ZONE_COLOURS,
    background,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)

FUNCTIONAL_BUCKETS: dict[str, list[str]] = {
    "primary_use": ["sofa", "bed", "dining_table", "desk", "conference_table"],
    "secondary_use": ["chair", "dining_chair", "lounge_chair", "office_chair", "coffee_table", "side_table", "console_table"],
    "storage": ["bookshelf", "wardrobe", "cabinet", "tv_unit", "media_console"],
    "accent": ["rug", "plant", "wall_art", "floor_lamp", "lamp", "sculpture"],
}


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
    body.append(title_block(40, 36, "Hierarchy", "Visual (size)   |   Material (share)   |   Functional (role)", width=canvas_w - 80))

    # Three rows.
    row_h = 140
    row_y = 90

    body.append(_visual_row(graph, 40, row_y, canvas_w - 80, row_h))
    body.append(_material_row(graph, 40, row_y + row_h + 20, canvas_w - 80, row_h))
    body.append(_functional_row(graph, 40, row_y + 2 * (row_h + 20), canvas_w - 80, row_h))

    svg = svg_open(canvas_w, canvas_h, title="Hierarchy") + "".join(body) + svg_close()
    return {"id": "hierarchy", "name": "Hierarchy", "format": "svg", "svg": svg, "meta": {"object_count": len(graph.get("objects", []))}}


def _visual_row(graph: dict, x: float, y: float, w: float, h: float) -> str:
    objs = sorted(graph.get("objects", []), key=_vol, reverse=True)[:6]
    parts = [text(x, y - 6, "VISUAL HIERARCHY", size=9, weight="600", fill=INK_SOFT)]
    if not objs:
        parts.append(text(x, y + h / 2, "(no objects)", size=11, fill=INK_MUTED))
        return "".join(parts)
    max_v = _vol(objs[0]) or 1.0
    cursor_x = x
    gap = 10
    available = w - gap * (len(objs) - 1)
    for i, obj in enumerate(objs):
        ratio = _vol(obj) / max_v
        bw = (available / len(objs))
        bh = h * (0.35 + 0.6 * ratio)
        colour = ZONE_COLOURS[i % len(ZONE_COLOURS)]
        parts.append(rect(cursor_x, y + h - bh, bw, bh, fill=colour, stroke=INK_SOFT, stroke_width=0.5, opacity=0.9))
        parts.append(text(cursor_x + bw / 2, y + h + 14, (obj.get("type") or "?").replace("_", " "), size=9, fill=INK_SOFT, anchor="middle"))
        parts.append(text(cursor_x + bw / 2, y + h - bh - 4, f"{_vol(obj):.2f} m³", size=8, fill=INK_MUTED, anchor="middle"))
        cursor_x += bw + gap
    return "".join(parts)


def _material_row(graph: dict, x: float, y: float, w: float, h: float) -> str:
    # Share by footprint area per material name (fallback: by object count).
    shares: dict[str, float] = {}
    for obj in graph.get("objects", []):
        mat = (obj.get("material") or "unassigned").split("_")[0].title() or "Unassigned"
        d = obj.get("dimensions") or {}
        footprint = _m(d.get("length")) * _m(d.get("width")) or 0.3
        shares[mat] = shares.get(mat, 0.0) + footprint
    parts = [text(x, y - 6, "MATERIAL HIERARCHY", size=9, weight="600", fill=INK_SOFT)]
    total = sum(shares.values()) or 1.0
    bar_y = y + h / 2 - 18
    bar_h = 28
    cursor = x
    for i, (mat, share) in enumerate(sorted(shares.items(), key=lambda s: -s[1])):
        seg = w * (share / total)
        colour = ZONE_COLOURS[i % len(ZONE_COLOURS)]
        parts.append(rect(cursor, bar_y, seg, bar_h, fill=colour, stroke=INK_SOFT, stroke_width=0.5))
        pct = 100 * share / total
        if seg > 60:
            parts.append(text(cursor + seg / 2, bar_y + bar_h / 2 + 4, f"{mat}  {pct:.0f}%", size=10, fill=INK, anchor="middle"))
        cursor += seg
    return "".join(parts)


def _functional_row(graph: dict, x: float, y: float, w: float, h: float) -> str:
    counts: dict[str, int] = {}
    for obj in graph.get("objects", []):
        bucket = _functional_bucket(obj.get("type"))
        counts[bucket] = counts.get(bucket, 0) + 1
    order = ["primary_use", "secondary_use", "storage", "accent"]
    counts_ordered = [(b, counts.get(b, 0)) for b in order]
    parts = [text(x, y - 6, "FUNCTIONAL HIERARCHY", size=9, weight="600", fill=INK_SOFT)]
    total = sum(c for _, c in counts_ordered) or 1
    bar_y = y + h / 2 - 18
    bar_h = 28
    cursor = x
    colours = ["#5a4632", "#8a6a3b", "#b79a74", "#d7c3a6"]
    for i, (bucket, n) in enumerate(counts_ordered):
        seg = w * (n / total) if total else 0
        if seg <= 0:
            continue
        parts.append(rect(cursor, bar_y, seg, bar_h, fill=colours[i], stroke=INK_SOFT, stroke_width=0.5))
        label = bucket.replace("_", " ").title()
        if seg > 70:
            parts.append(text(cursor + seg / 2, bar_y + bar_h / 2 + 4, f"{label}  ({n})", size=10, fill=PAPER, anchor="middle"))
        cursor += seg
    return "".join(parts)
