"""Plan-view technical drawing renderer (BRD Layer 3A #1).

Produces a CAD-style top-down sheet:
  • Room outline + object footprints with scale-aware geometry
  • Overall dimension chains (width × depth) with dim-line + arrowheads
  • Section reference markers (cut lines + bubbles) at LLM-chosen positions
  • Hatched material zones per LLM-supplied palette key
  • Scale bar + title block + sheet metadata

Pure deterministic — no I/O, no LLM. The LLM-authored spec drives WHAT
to annotate; this module decides HOW to draw it.
"""

from __future__ import annotations

from typing import Any

from app.services.diagrams.svg_base import (
    INK,
    INK_MUTED,
    INK_SOFT,
    PAPER,
    PAPER_DEEP,
    background,
    circle,
    compute_plan_transform,
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)

# Hatch vocabulary — keyed so LLM picks names from a catalogue.
HATCH_PATTERNS: dict[str, dict[str, str]] = {
    "wood":     {"angle": "45",  "spacing": "6",  "stroke": "#8a6a3b"},
    "stone":    {"angle": "0",   "spacing": "8",  "stroke": "#666666"},
    "concrete": {"angle": "90",  "spacing": "10", "stroke": "#888888"},
    "metal":    {"angle": "135", "spacing": "5",  "stroke": "#3b3b3b"},
    "fabric":   {"angle": "30",  "spacing": "7",  "stroke": "#7a5a4a"},
    "tile":     {"angle": "0",   "spacing": "12", "stroke": "#5a7a8a"},
    "glass":    {"angle": "60",  "spacing": "9",  "stroke": "#3a6a7a"},
}

DIMENSION_OFFSET_PX = 28
ARROW_HALF = 4
SCALE_OPTIONS = ("1:10", "1:20", "1:50", "1:100")


def _m(value: Any) -> float:
    """Coerce to metres — accept mm (>20) or m (<=20)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _hatch_defs() -> str:
    """SVG <pattern> defs for every hatch in the vocabulary."""
    parts = ['<defs>']
    for name, spec in HATCH_PATTERNS.items():
        spacing = float(spec["spacing"])
        angle = spec["angle"]
        stroke = spec["stroke"]
        parts.append(
            f'<pattern id="hatch-{name}" patternUnits="userSpaceOnUse" '
            f'width="{spacing}" height="{spacing}" patternTransform="rotate({angle})">'
            f'<line x1="0" y1="0" x2="0" y2="{spacing}" stroke="{stroke}" stroke-width="0.6"/>'
            f'</pattern>'
        )
    # Triangle arrowhead for dimension chains.
    parts.append(
        '<marker id="dim-arrow" markerWidth="8" markerHeight="8" '
        'refX="6" refY="4" orient="auto" markerUnits="userSpaceOnUse">'
        '<path d="M 0 0 L 6 4 L 0 8 Z" fill="#1f1d1a"/>'
        '</marker>'
    )
    parts.append('</defs>')
    return "".join(parts)


def _dim_chain(x1: float, y1: float, x2: float, y2: float, label: str) -> str:
    """Render a dimension chain (extension + dim line + arrows + label)."""
    parts: list[str] = []
    # Main dimension line with arrowheads at both ends.
    parts.append(
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{INK}" stroke-width="0.6" '
        f'marker-start="url(#dim-arrow)" marker-end="url(#dim-arrow)"/>'
    )
    # Label above the line (horizontal) or beside it (vertical).
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    if abs(x2 - x1) > abs(y2 - y1):
        parts.append(text(cx, cy - 6, label, size=10, fill=INK, anchor="middle", weight="600"))
    else:
        parts.append(text(cx + 8, cy + 4, label, size=10, fill=INK, anchor="start", weight="600"))
    return "".join(parts)


def _section_marker(x: float, y: float, label: str, axis: str = "x") -> str:
    """Section bubble + cut line marker (e.g. A-A)."""
    parts: list[str] = []
    parts.append(circle(x, y, 8, fill=PAPER_DEEP))
    parts.append(circle(x, y, 8, fill="none"))
    # Outline with INK stroke.
    parts.append(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="8" fill="none" stroke="{INK}" stroke-width="0.8"/>'
    )
    parts.append(text(x, y + 3, label, size=9, fill=INK, anchor="middle", weight="700"))
    return "".join(parts)


def _scale_bar(x: float, y: float, scale_label: str, mm_per_metre_at_scale: float = 100.0) -> str:
    """Five-segment alternating scale bar with metric labels.

    `mm_per_metre_at_scale` is purely a visual length cue on the sheet —
    we draw a 5-tick bar at a fixed ~120 px width regardless of scale,
    label it with the equivalent metric distance.
    """
    parts: list[str] = []
    bar_w = 120
    bar_h = 8
    seg_w = bar_w / 5
    for i in range(5):
        fill = INK if i % 2 == 0 else "white"
        parts.append(rect(x + i * seg_w, y, seg_w, bar_h, fill=fill, stroke=INK, stroke_width=0.6))
    # Tick labels — 0, 1m, 2m, 3m, 4m, 5m for 1:50 default.
    metres_per_seg = {"1:10": 0.2, "1:20": 0.4, "1:50": 1.0, "1:100": 2.0}.get(scale_label, 1.0)
    for i in range(6):
        tx = x + i * seg_w
        parts.append(line(tx, y - 2, tx, y + bar_h + 2, stroke=INK, stroke_width=0.5))
        parts.append(text(tx, y + bar_h + 14, f"{i*metres_per_seg:.1f}m", size=8, fill=INK_SOFT, anchor="middle"))
    parts.append(text(x, y - 6, f"Scale {scale_label}", size=9, fill=INK, weight="600"))
    return "".join(parts)


def _pick_scale(longest_edge_m: float) -> str:
    """Pick a sane scale band based on the longest room edge.

    BRD Plan View calls for 1:10 or 1:20 (small detail piece). For room
    plans the nearest CAD convention is 1:50 / 1:100.
    """
    if longest_edge_m <= 1.5:
        return "1:10"
    if longest_edge_m <= 3.0:
        return "1:20"
    if longest_edge_m <= 8.0:
        return "1:50"
    return "1:100"


def render_plan_view(
    *,
    graph: dict,
    plan_spec: dict | None = None,
    canvas_w: int = 1100,
    canvas_h: int = 720,
    sheet_title: str = "Plan View",
) -> dict:
    """Render the plan-view sheet from a graph + an optional LLM plan_spec.

    plan_spec (LLM-authored, optional) carries:
      - scale (string from SCALE_OPTIONS)
      - key_dimensions: [{label, axis: "x"|"z"}]   # which dims to call out
      - section_references: [{label, position: "x"|"z" + ratio 0..1, axis}]
      - material_zones: [{object_type, hatch_key}]
    """
    spec = plan_spec or {}
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    room_l = float(dims.get("length") or 6.0)
    room_w = float(dims.get("width") or 4.0)

    scale_label = spec.get("scale") or _pick_scale(max(room_l, room_w))
    scale_px, tx, ty = compute_plan_transform(room_l, room_w, canvas_w - 280, canvas_h - 220, margin=80)
    room_px_w = room_l * scale_px
    room_px_h = room_w * scale_px

    body: list[str] = [
        background(canvas_w, canvas_h, fill=PAPER),
        _hatch_defs(),
        title_block(40, 36, sheet_title, f"Room: {room_l:.2f} × {room_w:.2f} m  |  Scale {scale_label}", width=canvas_w - 80),
    ]

    # Hatch lookup by object type from plan_spec.material_zones.
    hatch_for_type: dict[str, str] = {}
    for z in spec.get("material_zones") or []:
        otype = (z.get("object_type") or "").lower()
        key = (z.get("hatch_key") or "").lower()
        if otype and key in HATCH_PATTERNS:
            hatch_for_type[otype] = key

    # Room outline.
    body.append(rect(tx, ty, room_px_w, room_px_h, fill="none", stroke=INK, stroke_width=1.6))

    # Object footprints (filled with hatch if mapped).
    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "").lower()
        d = obj.get("dimensions") or {}
        p = obj.get("position") or {}
        ox = float(p.get("x", 0)) * scale_px + tx
        oz = float(p.get("z", 0)) * scale_px + ty
        ow = (_m(d.get("length")) or 0.4) * scale_px
        oh = (_m(d.get("width")) or 0.3) * scale_px
        hatch_key = hatch_for_type.get(otype)
        fill = f"url(#hatch-{hatch_key})" if hatch_key else "none"
        body.append(rect(
            ox - ow / 2, oz - oh / 2, ow, oh,
            fill=fill, stroke=INK_SOFT, stroke_width=0.7,
        ))
        body.append(text(ox, oz + 3, otype.replace("_", " "), size=9, fill=INK, anchor="middle"))

    # Overall dimension chains — width along top, depth along right.
    body.append(_dim_chain(
        tx, ty - DIMENSION_OFFSET_PX,
        tx + room_px_w, ty - DIMENSION_OFFSET_PX,
        f"{room_l:.2f} m",
    ))
    body.append(_dim_chain(
        tx + room_px_w + DIMENSION_OFFSET_PX, ty,
        tx + room_px_w + DIMENSION_OFFSET_PX, ty + room_px_h,
        f"{room_w:.2f} m",
    ))

    # Extension lines (thin solid from corners to dim line).
    for x in (tx, tx + room_px_w):
        body.append(line(x, ty, x, ty - DIMENSION_OFFSET_PX - 4, stroke=INK_SOFT, stroke_width=0.4))
    for y in (ty, ty + room_px_h):
        body.append(line(tx + room_px_w, y, tx + room_px_w + DIMENSION_OFFSET_PX + 4, y, stroke=INK_SOFT, stroke_width=0.4))

    # Section reference markers from spec.
    sections_drawn: list[str] = []
    for s in spec.get("section_references") or []:
        label = (s.get("label") or "A").upper()
        axis = (s.get("axis") or "x").lower()
        ratio = max(0.0, min(1.0, float(s.get("position") or 0.5)))
        if axis == "x":
            x = tx + ratio * room_px_w
            # Vertical cut line.
            body.append(line(x, ty - 12, x, ty + room_px_h + 12, stroke=INK, stroke_width=0.6, dash="6 3"))
            body.append(_section_marker(x, ty - 16, label))
            body.append(_section_marker(x, ty + room_px_h + 16, label))
        else:
            y = ty + ratio * room_px_h
            body.append(line(tx - 12, y, tx + room_px_w + 12, y, stroke=INK, stroke_width=0.6, dash="6 3"))
            body.append(_section_marker(tx - 16, y, label))
            body.append(_section_marker(tx + room_px_w + 16, y, label))
        sections_drawn.append(label)

    # Scale bar + sheet meta in lower-left.
    body.append(_scale_bar(40, canvas_h - 70, scale_label))

    # Hatch legend in lower-right.
    legend_x = canvas_w - 240
    legend_y = canvas_h - 110
    body.append(text(legend_x, legend_y, "Material zones", size=11, fill=INK, weight="600"))
    used_hatches = {hatch_for_type[t] for t in hatch_for_type}
    for i, key in enumerate(sorted(used_hatches)):
        yy = legend_y + 16 + i * 18
        body.append(rect(legend_x, yy - 10, 24, 14, fill=f"url(#hatch-{key})", stroke=INK_SOFT, stroke_width=0.5))
        body.append(text(legend_x + 30, yy, key, size=10, fill=INK))

    svg = svg_open(canvas_w, canvas_h, title=sheet_title) + "".join(body) + svg_close()
    return {
        "id": "plan_view",
        "name": "Plan View",
        "format": "svg",
        "svg": svg,
        "meta": {
            "scale": scale_label,
            "room_length_m": round(room_l, 3),
            "room_width_m": round(room_w, 3),
            "object_count": len(graph.get("objects", [])),
            "section_labels": sections_drawn,
            "hatched_object_types": sorted(hatch_for_type.keys()),
        },
    }
