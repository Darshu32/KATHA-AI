"""Elevation-view technical drawing renderer (BRD Layer 3A #2).

Front or side projection of a single piece (or a wall of objects).
Produces a CAD-style sheet with:
  • Vertical projection of the bounding mass + (optional) leg/base zone
  • Height dimensions on the right side (overall, seat, back, etc.)
  • Width dimensions on the bottom
  • Hardware callouts (bubble + leader line)
  • Detail callouts (dashed circle + leader + key)
  • Scale bar + title block

Pure deterministic. The LLM-authored elevation_spec drives WHAT to
annotate; this module decides HOW to draw it.
"""

from __future__ import annotations

from typing import Any

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
from app.services.drawings.plan_view import (
    HATCH_PATTERNS,
    SCALE_OPTIONS,
    _hatch_defs,
    _scale_bar,
)

VIEW_FRONT = "front"
VIEW_SIDE = "side"
VIEW_OPTIONS = (VIEW_FRONT, VIEW_SIDE)

DIM_OFFSET = 32
ARROW_HALF = 4


def _mm(value: Any) -> float:
    """Coerce to mm — accept m (<20) or mm (>=20)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v * 1000.0 if 0 < v < 20 else v


def _pick_scale(longest_edge_mm: float) -> str:
    if longest_edge_mm <= 1500:
        return "1:10"
    if longest_edge_mm <= 3000:
        return "1:20"
    if longest_edge_mm <= 8000:
        return "1:50"
    return "1:100"


def _v_dim(x: float, y_top: float, y_bottom: float, label: str) -> str:
    """Vertical dimension chain — used for heights (right side of piece)."""
    parts: list[str] = []
    parts.append(
        f'<line x1="{x:.2f}" y1="{y_top:.2f}" x2="{x:.2f}" y2="{y_bottom:.2f}" '
        f'stroke="{INK}" stroke-width="0.6" '
        f'marker-start="url(#dim-arrow)" marker-end="url(#dim-arrow)"/>'
    )
    cy = (y_top + y_bottom) / 2
    parts.append(text(x + 8, cy + 4, label, size=10, fill=INK, anchor="start", weight="600"))
    return "".join(parts)


def _h_dim(x_left: float, x_right: float, y: float, label: str) -> str:
    """Horizontal dimension chain — used for widths (under piece)."""
    parts: list[str] = []
    parts.append(
        f'<line x1="{x_left:.2f}" y1="{y:.2f}" x2="{x_right:.2f}" y2="{y:.2f}" '
        f'stroke="{INK}" stroke-width="0.6" '
        f'marker-start="url(#dim-arrow)" marker-end="url(#dim-arrow)"/>'
    )
    cx = (x_left + x_right) / 2
    parts.append(text(cx, y - 6, label, size=10, fill=INK, anchor="middle", weight="600"))
    return "".join(parts)


def _hardware_callout(x: float, y: float, label: str, key: str) -> str:
    """Small bubble + leader for a hardware location (handle, hinge, etc.)."""
    parts: list[str] = []
    parts.append(circle(x, y, 3, fill=ACCENT_WARM))
    parts.append(line(x, y, x + 24, y - 18, stroke=INK_SOFT, stroke_width=0.5))
    parts.append(circle(x + 24, y - 18, 9, fill=PAPER_DEEP))
    parts.append(
        f'<circle cx="{x + 24:.2f}" cy="{y - 18:.2f}" r="9" fill="none" stroke="{INK}" stroke-width="0.7"/>'
    )
    parts.append(text(x + 24, y - 15, key, size=9, fill=INK, anchor="middle", weight="700"))
    parts.append(text(x + 36, y - 16, label, size=9, fill=INK_SOFT, anchor="start"))
    return "".join(parts)


def _detail_callout(x: float, y: float, key: str, label: str) -> str:
    """Dashed circle around an area + leader + key (e.g. D1, D2)."""
    parts: list[str] = []
    parts.append(
        f'<circle cx="{x:.2f}" cy="{y:.2f}" r="14" fill="none" stroke="{INK}" '
        f'stroke-width="0.7" stroke-dasharray="3 2"/>'
    )
    parts.append(line(x + 14, y, x + 40, y - 22, stroke=INK_SOFT, stroke_width=0.5))
    parts.append(circle(x + 40, y - 22, 11, fill=PAPER_DEEP))
    parts.append(
        f'<circle cx="{x + 40:.2f}" cy="{y - 22:.2f}" r="11" fill="none" stroke="{INK}" stroke-width="0.7"/>'
    )
    parts.append(text(x + 40, y - 19, key, size=10, fill=INK, anchor="middle", weight="700"))
    parts.append(text(x + 54, y - 20, label, size=9, fill=INK_SOFT, anchor="start"))
    return "".join(parts)


def render_elevation_view(
    *,
    piece: dict | None = None,
    graph: dict | None = None,
    elevation_spec: dict | None = None,
    canvas_w: int = 1100,
    canvas_h: int = 720,
    sheet_title: str = "Elevation View",
) -> dict:
    """Render the elevation sheet from a piece envelope or a design graph.

    `piece` shape (preferred for furniture-scale BRD use-case):
        {
            "type": "lounge_chair",
            "dimensions_mm": {"length": 800, "width": 850, "height": 750},
            "ergonomic_targets_mm": {"seat_height_mm": 380, "back_height_mm": 750, "leg_base_mm": 100, "arm_height_mm": 600},
            "material_hatch_key": "wood",       # optional
            "leg_base_hatch_key": "metal",      # optional
        }

    `graph` fallback: project the room itself (height = ceiling, width = chosen-axis room edge).

    elevation_spec (LLM-authored) carries:
        view ("front" | "side"), scale, height_dimensions[], width_dimensions[],
        hardware_callouts[], detail_callouts[], proportions[].
    """
    spec = elevation_spec or {}
    view = (spec.get("view") or VIEW_FRONT).lower()
    if view not in VIEW_OPTIONS:
        view = VIEW_FRONT

    # Resolve the piece envelope.
    if piece is None and graph is not None:
        room = graph.get("room") or (graph.get("spaces") or [{}])[0]
        d = room.get("dimensions") or {}
        # Front view = looking at the long wall (length × height); side view = (width × height).
        edge_mm = (float(d.get("length") or 6.0) if view == VIEW_FRONT else float(d.get("width") or 4.0)) * 1000.0
        height_mm = float(d.get("height") or 2.7) * 1000.0
        piece = {
            "type": (room.get("type") or "room"),
            "dimensions_mm": {
                "length": edge_mm,
                "width": (float(d.get("width") or 4.0) if view == VIEW_FRONT else float(d.get("length") or 6.0)) * 1000.0,
                "height": height_mm,
            },
        }
    elif piece is None:
        piece = {"type": "piece", "dimensions_mm": {"length": 800, "width": 800, "height": 750}}

    dims_mm = piece.get("dimensions_mm") or {}
    overall_h = _mm(dims_mm.get("height") or 750)
    width_for_view = _mm(dims_mm.get("length") if view == VIEW_FRONT else dims_mm.get("width") or 800)

    scale_label = spec.get("scale") or _pick_scale(max(overall_h, width_for_view))
    # Visual scale factor — fit piece into canvas drawing area.
    draw_w = canvas_w - 360
    draw_h = canvas_h - 220
    scale_px = min(draw_w / width_for_view, draw_h / overall_h)
    px_w = width_for_view * scale_px
    px_h = overall_h * scale_px
    tx = 80
    ty = 110 + (draw_h - px_h) / 2

    body: list[str] = [
        background(canvas_w, canvas_h, fill=PAPER),
        _hatch_defs(),
        title_block(
            40, 36,
            sheet_title,
            f"{piece.get('type', 'piece').replace('_', ' ').title()} — {view.title()} elevation  |  Scale {scale_label}",
            width=canvas_w - 80,
        ),
    ]

    # Body (the piece silhouette).
    body_hatch = piece.get("material_hatch_key")
    body_fill = f"url(#hatch-{body_hatch})" if body_hatch in HATCH_PATTERNS else "none"
    body.append(rect(tx, ty, px_w, px_h, fill=body_fill, stroke=INK, stroke_width=1.4))

    # Optional leg/base zone — drawn as a band at the bottom if leg_base_mm given.
    ergo = piece.get("ergonomic_targets_mm") or {}
    leg_base_mm = ergo.get("leg_base_mm")
    if leg_base_mm:
        leg_h_px = _mm(leg_base_mm) * scale_px
        leg_hatch = piece.get("leg_base_hatch_key")
        leg_fill = f"url(#hatch-{leg_hatch})" if leg_hatch in HATCH_PATTERNS else PAPER_DEEP
        body.append(rect(tx, ty + px_h - leg_h_px, px_w, leg_h_px, fill=leg_fill, stroke=INK_SOFT, stroke_width=0.6, opacity=0.85))
        body.append(text(tx + px_w + 6, ty + px_h - leg_h_px / 2 + 3, "Base", size=9, fill=INK_SOFT))

    # Optional seat-line guide (horizontal dashed line at seat height).
    seat_h_mm = ergo.get("seat_height_mm")
    if seat_h_mm:
        seat_y = ty + px_h - _mm(seat_h_mm) * scale_px
        body.append(line(tx - 8, seat_y, tx + px_w + 8, seat_y, stroke=INK_SOFT, stroke_width=0.5, dash="5 3"))
        body.append(text(tx - 12, seat_y + 3, "seat", size=9, fill=INK_SOFT, anchor="end"))

    back_h_mm = ergo.get("back_height_mm")
    if back_h_mm:
        back_y = ty + px_h - _mm(back_h_mm) * scale_px
        body.append(line(tx - 8, back_y, tx + px_w + 8, back_y, stroke=INK_SOFT, stroke_width=0.5, dash="5 3"))
        body.append(text(tx - 12, back_y + 3, "back", size=9, fill=INK_SOFT, anchor="end"))

    # Height dimensions on the right side. LLM-supplied chain takes priority;
    # otherwise we draw the overall height.
    dim_x = tx + px_w + DIM_OFFSET
    height_dims = spec.get("height_dimensions") or [
        {"label": f"{overall_h:.0f} mm", "from_mm": 0, "to_mm": overall_h}
    ]
    # Sort by ascending from_mm so we can stagger the X if any chain overlaps.
    for i, d in enumerate(height_dims[:6]):
        from_mm = float(d.get("from_mm") or 0)
        to_mm = float(d.get("to_mm") or overall_h)
        # Y in SVG grows down; floor is at ty + px_h.
        y_bottom = ty + px_h - from_mm * scale_px
        y_top = ty + px_h - to_mm * scale_px
        x = dim_x + i * 16  # stagger to avoid overlap
        body.append(_v_dim(x, y_top, y_bottom, str(d.get("label") or f"{to_mm - from_mm:.0f} mm")))
        # Extension lines from piece edge to the dim line.
        body.append(line(tx + px_w, y_bottom, x + 4, y_bottom, stroke=INK_SOFT, stroke_width=0.4))
        body.append(line(tx + px_w, y_top, x + 4, y_top, stroke=INK_SOFT, stroke_width=0.4))

    # Width dimensions under the piece. LLM-supplied chains take priority;
    # otherwise the overall width.
    bottom_dim_y = ty + px_h + DIM_OFFSET
    width_dims = spec.get("width_dimensions") or [
        {"label": f"{width_for_view:.0f} mm", "from_mm": 0, "to_mm": width_for_view}
    ]
    for i, d in enumerate(width_dims[:6]):
        from_mm = float(d.get("from_mm") or 0)
        to_mm = float(d.get("to_mm") or width_for_view)
        x_left = tx + from_mm * scale_px
        x_right = tx + to_mm * scale_px
        y = bottom_dim_y + i * 16
        body.append(_h_dim(x_left, x_right, y, str(d.get("label") or f"{to_mm - from_mm:.0f} mm")))
        body.append(line(x_left, ty + px_h, x_left, y - 4, stroke=INK_SOFT, stroke_width=0.4))
        body.append(line(x_right, ty + px_h, x_right, y - 4, stroke=INK_SOFT, stroke_width=0.4))

    # Hardware callouts.
    hw_keys: list[str] = []
    for i, hw in enumerate((spec.get("hardware_callouts") or [])[:8]):
        x_ratio = max(0.0, min(1.0, float(hw.get("x_ratio") or 0.5)))
        y_ratio = max(0.0, min(1.0, float(hw.get("y_ratio") or 0.5)))
        x = tx + x_ratio * px_w
        y = ty + (1.0 - y_ratio) * px_h  # y_ratio=0 → floor, 1 → top
        key = (hw.get("key") or f"H{i+1}").upper()
        body.append(_hardware_callout(x, y, hw.get("label") or "", key))
        hw_keys.append(key)

    # Detail callouts.
    detail_keys: list[str] = []
    for i, dt in enumerate((spec.get("detail_callouts") or [])[:6]):
        x_ratio = max(0.0, min(1.0, float(dt.get("x_ratio") or 0.5)))
        y_ratio = max(0.0, min(1.0, float(dt.get("y_ratio") or 0.5)))
        x = tx + x_ratio * px_w
        y = ty + (1.0 - y_ratio) * px_h
        key = (dt.get("key") or f"D{i+1}").upper()
        body.append(_detail_callout(x, y, key, dt.get("label") or ""))
        detail_keys.append(key)

    # Scale bar lower-left.
    body.append(_scale_bar(40, canvas_h - 70, scale_label))

    # Right-side meta panel — proportions list.
    proportions = spec.get("proportions") or []
    if proportions:
        meta_x = canvas_w - 240
        meta_y = 130
        body.append(rect(meta_x - 12, meta_y - 18, 232, 24 + 18 * len(proportions[:6]), fill="white", stroke=INK_SOFT, stroke_width=0.5, opacity=0.9))
        body.append(text(meta_x, meta_y, "Key proportions", size=11, fill=INK, weight="600"))
        for i, p in enumerate(proportions[:6]):
            yy = meta_y + 16 + i * 18
            body.append(text(meta_x, yy, str(p.get("name") or ""), size=10, fill=INK, weight="600"))
            body.append(text(meta_x + 130, yy, str(p.get("value") or ""), size=10, fill=INK_SOFT, anchor="end"))

    svg = svg_open(canvas_w, canvas_h, title=sheet_title) + "".join(body) + svg_close()
    return {
        "id": "elevation_view",
        "name": "Elevation View",
        "format": "svg",
        "svg": svg,
        "meta": {
            "view": view,
            "scale": scale_label,
            "overall_height_mm": round(overall_h, 1),
            "width_for_view_mm": round(width_for_view, 1),
            "hardware_callout_keys": hw_keys,
            "detail_callout_keys": detail_keys,
            "height_dim_count": len(height_dims),
            "width_dim_count": len(width_dims),
        },
    }
