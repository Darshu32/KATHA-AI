"""Section-view technical drawing renderer (BRD Layer 3A #3).

Cut-through detail drawing showing what the elevation hides — frame
joints, reinforcement, foam / upholstery layers, leg taper geometry,
back-rest angle. Operates at a tighter scale (1:5 / 1:10) than plan
or elevation views.

Sheet contents:
  • Outer silhouette of the cut piece (same projection axis as elevation)
  • Layered fills inside the silhouette (LLM-supplied stack: outer→inner)
  • Joint markers at LLM-supplied positions with joinery key (M&T, DOW…)
  • Reinforcement marks (corner block, bracket, dowel) with leader keys
  • Dim chain for seat depth (horizontal) + back angle (degree marker)
  • Leg taper dim chain (top vs bottom width) when supplied
  • Layer legend, scale bar, title block

Pure deterministic. The LLM-authored section_spec drives WHAT to show;
this module decides HOW to draw it.
"""

from __future__ import annotations

from math import cos, radians, sin
from typing import Any

from app.services.diagrams.svg_base import (
    ACCENT_COOL,
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
from app.services.drawings.elevation_view import (
    _h_dim,
    _v_dim,
)
from app.services.drawings.plan_view import (
    HATCH_PATTERNS,
    _hatch_defs,
    _scale_bar,
)

SECTION_SCALE_OPTIONS = ("1:5", "1:10", "1:20")
DIM_OFFSET = 28

# Joinery vocabulary the LLM picks from. Mirrors knowledge.manufacturing.JOINERY keys.
JOINERY_KEYS = (
    "mortise_tenon",
    "dovetail",
    "pocket_hole",
    "dowel",
    "biscuit",
    "butt_screw",
    "finger_joint",
)

REINFORCEMENT_TYPES = (
    "corner_block",
    "bracket",
    "dowel",
    "screw",
    "glue_block",
    "metal_strap",
)


def _mm(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v * 1000.0 if 0 < v < 20 else v


def _pick_scale(longest_edge_mm: float) -> str:
    if longest_edge_mm <= 800:
        return "1:5"
    if longest_edge_mm <= 2000:
        return "1:10"
    return "1:20"


def _joint_marker(x: float, y: float, key: str, label: str) -> str:
    """Joint diamond + key bubble."""
    parts: list[str] = []
    # Diamond marker on the joint location.
    d = 10
    parts.append(
        f'<polygon points="{x:.2f},{y - d:.2f} {x + d:.2f},{y:.2f} '
        f'{x:.2f},{y + d:.2f} {x - d:.2f},{y:.2f}" '
        f'fill="{ACCENT_WARM}" stroke="{INK}" stroke-width="0.7"/>'
    )
    parts.append(line(x + 8, y, x + 36, y - 24, stroke=INK_SOFT, stroke_width=0.5))
    parts.append(circle(x + 36, y - 24, 12, fill=PAPER_DEEP))
    parts.append(
        f'<circle cx="{x + 36:.2f}" cy="{y - 24:.2f}" r="12" fill="none" '
        f'stroke="{INK}" stroke-width="0.7"/>'
    )
    parts.append(text(x + 36, y - 21, key, size=10, fill=INK, anchor="middle", weight="700"))
    parts.append(text(x + 52, y - 22, label, size=9, fill=INK_SOFT, anchor="start"))
    return "".join(parts)


def _reinforcement_marker(x: float, y: float, key: str, label: str) -> str:
    """Square marker + key bubble for reinforcement (corner block, bracket, etc.)."""
    parts: list[str] = []
    parts.append(rect(x - 6, y - 6, 12, 12, fill=ACCENT_COOL, stroke=INK, stroke_width=0.7))
    parts.append(line(x + 6, y, x + 32, y + 22, stroke=INK_SOFT, stroke_width=0.5))
    parts.append(circle(x + 32, y + 22, 12, fill=PAPER_DEEP))
    parts.append(
        f'<circle cx="{x + 32:.2f}" cy="{y + 22:.2f}" r="12" fill="none" '
        f'stroke="{INK}" stroke-width="0.7"/>'
    )
    parts.append(text(x + 32, y + 25, key, size=10, fill=INK, anchor="middle", weight="700"))
    parts.append(text(x + 48, y + 24, label, size=9, fill=INK_SOFT, anchor="start"))
    return "".join(parts)


def _angle_marker(cx: float, cy: float, angle_deg: float, label: str, radius: float = 28) -> str:
    """Arc + label for back-rest angle (measured from vertical)."""
    parts: list[str] = []
    # Reference vertical line.
    parts.append(line(cx, cy, cx, cy - radius - 6, stroke=INK_MUTED, stroke_width=0.5, dash="3 2"))
    # Angled line (back-rest direction).
    end_x = cx + radius * sin(radians(angle_deg))
    end_y = cy - radius * cos(radians(angle_deg))
    parts.append(line(cx, cy, end_x, end_y, stroke=INK, stroke_width=1.0))
    # Arc from vertical to angled line.
    arc = (
        f'<path d="M {cx:.2f},{cy - radius:.2f} A {radius:.2f},{radius:.2f} 0 0 1 '
        f'{end_x:.2f},{end_y:.2f}" fill="none" stroke="{INK}" stroke-width="0.8"/>'
    )
    parts.append(arc)
    parts.append(text(cx + radius * 0.55, cy - radius * 0.55, label, size=10, fill=INK, weight="600"))
    return "".join(parts)


def render_section_view(
    *,
    piece: dict | None = None,
    section_spec: dict | None = None,
    canvas_w: int = 1200,
    canvas_h: int = 760,
    sheet_title: str = "Section View",
) -> dict:
    """Render the section sheet from a piece envelope + LLM-authored section_spec.

    `piece` is the same envelope shape used by elevation_view:
        {type, dimensions_mm, ergonomic_targets_mm, material_hatch_key, leg_base_hatch_key}

    `section_spec` (LLM-authored) carries:
        cut_label (e.g. "A-A"), view_target (through_seat / through_arm / etc.),
        scale, key_dimensions[], back_angle_deg, leg_taper_mm,
        internal_layers[], joints[], reinforcement[], detail_callouts[].
    """
    spec = section_spec or {}
    piece = piece or {"type": "piece", "dimensions_mm": {"length": 800, "width": 800, "height": 750}}
    dims = piece.get("dimensions_mm") or {}
    overall_h = _mm(dims.get("height") or 750)
    overall_w = _mm(dims.get("length") or dims.get("width") or 800)

    scale_label = spec.get("scale") or _pick_scale(max(overall_h, overall_w))

    # Geometry — keep the silhouette in the left half of the sheet so we
    # have room for layer legend + reinforcement keys on the right.
    draw_w = canvas_w - 460
    draw_h = canvas_h - 220
    scale_px = min(draw_w / overall_w, draw_h / overall_h)
    px_w = overall_w * scale_px
    px_h = overall_h * scale_px
    tx = 80
    ty = 110 + (draw_h - px_h) / 2

    body: list[str] = [
        background(canvas_w, canvas_h, fill=PAPER),
        _hatch_defs(),
        title_block(
            40, 36,
            sheet_title,
            f"{piece.get('type','piece').replace('_',' ').title()} — Section {spec.get('cut_label','A-A')}  |  Scale {scale_label}",
            width=canvas_w - 80,
        ),
    ]

    # Outer silhouette (cut outline drawn heavy).
    body.append(rect(tx, ty, px_w, px_h, fill="none", stroke=INK, stroke_width=1.6))

    # Internal layers — LLM supplies the order outer→inner, each occupying a
    # band proportional to layer.thickness_mm. We stack them inside the
    # silhouette from the seat surface downward (or wherever applicable).
    layers = spec.get("internal_layers") or []
    layer_origin = (spec.get("layer_origin") or "top").lower()  # top | bottom | full
    cursor = ty if layer_origin == "top" else ty + px_h
    total_layer_mm = sum(_mm(l.get("thickness_mm") or 0) for l in layers)
    if total_layer_mm > 0 and total_layer_mm <= overall_h:
        for i, layer in enumerate(layers[:8]):
            t_mm = _mm(layer.get("thickness_mm") or 0)
            if t_mm <= 0:
                continue
            t_px = t_mm * scale_px
            if layer_origin == "bottom":
                cursor -= t_px
                y = cursor
            else:
                y = cursor
                cursor += t_px
            hatch = (layer.get("hatch_key") or "").lower()
            fill = f"url(#hatch-{hatch})" if hatch in HATCH_PATTERNS else PAPER_DEEP
            body.append(rect(tx, y, px_w, t_px, fill=fill, stroke=INK_SOFT, stroke_width=0.5, opacity=0.9))
            label_y = y + t_px / 2 + 3
            body.append(text(tx + px_w + 8, label_y, layer.get("label") or hatch or "", size=9, fill=INK_SOFT))

    # Seat depth dim along the bottom (horizontal).
    seat_depth_mm = (spec.get("key_dimensions_mm") or {}).get("seat_depth_mm")
    if seat_depth_mm:
        x_left = tx
        x_right = tx + _mm(seat_depth_mm) * scale_px
        body.append(_h_dim(x_left, x_right, ty + px_h + DIM_OFFSET, f"Seat depth {seat_depth_mm:.0f}"))
        body.append(line(x_right, ty + px_h, x_right, ty + px_h + DIM_OFFSET - 4, stroke=INK_SOFT, stroke_width=0.4))

    # Back angle — angle marker near the upper-back corner.
    back_angle_deg = spec.get("back_angle_deg")
    if back_angle_deg:
        ang_cx = tx + px_w * 0.85
        ang_cy = ty + px_h * 0.25
        body.append(_angle_marker(ang_cx, ang_cy, float(back_angle_deg), f"{back_angle_deg:.0f}° back"))

    # Leg taper dim — two horizontal chains at top and bottom of the leg band.
    leg_taper_mm = spec.get("leg_taper_mm") or {}
    if leg_taper_mm.get("top") and leg_taper_mm.get("bottom"):
        # Draw inside the lower 18% of silhouette as a representative leg cross-section.
        leg_band_y = ty + px_h * 0.86
        leg_band_h = px_h * 0.10
        top_w = _mm(leg_taper_mm["top"]) * scale_px
        bot_w = _mm(leg_taper_mm["bottom"]) * scale_px
        cx = tx + px_w * 0.18  # representative leg position
        # Trapezoidal leg outline.
        body.append(
            f'<polygon points="{cx - top_w/2:.2f},{leg_band_y:.2f} '
            f'{cx + top_w/2:.2f},{leg_band_y:.2f} '
            f'{cx + bot_w/2:.2f},{leg_band_y + leg_band_h:.2f} '
            f'{cx - bot_w/2:.2f},{leg_band_y + leg_band_h:.2f}" '
            f'fill="url(#hatch-wood)" stroke="{INK}" stroke-width="0.8"/>'
        )
        body.append(text(cx, leg_band_y - 6, f"top {leg_taper_mm['top']:.0f}", size=9, fill=INK_SOFT, anchor="middle"))
        body.append(text(cx, leg_band_y + leg_band_h + 12, f"base {leg_taper_mm['bottom']:.0f}", size=9, fill=INK_SOFT, anchor="middle"))

    # Joint markers.
    joint_keys: list[str] = []
    for i, j in enumerate((spec.get("joints") or [])[:6]):
        x_ratio = max(0.0, min(1.0, float(j.get("x_ratio") or 0.5)))
        y_ratio = max(0.0, min(1.0, float(j.get("y_ratio") or 0.5)))
        x = tx + x_ratio * px_w
        y = ty + (1.0 - y_ratio) * px_h
        key = (j.get("key") or f"J{i+1}").upper()
        joinery = (j.get("joinery") or "joint").replace("_", " ")
        body.append(_joint_marker(x, y, key, joinery))
        joint_keys.append(key)

    # Reinforcement markers.
    reinf_keys: list[str] = []
    for i, r in enumerate((spec.get("reinforcement") or [])[:5]):
        x_ratio = max(0.0, min(1.0, float(r.get("x_ratio") or 0.5)))
        y_ratio = max(0.0, min(1.0, float(r.get("y_ratio") or 0.5)))
        x = tx + x_ratio * px_w
        y = ty + (1.0 - y_ratio) * px_h
        key = (r.get("key") or f"R{i+1}").upper()
        rtype = (r.get("type") or "reinf").replace("_", " ")
        body.append(_reinforcement_marker(x, y, key, rtype))
        reinf_keys.append(key)

    # Right-side legend panel — layer stack list (LLM order).
    legend_x = canvas_w - 240
    legend_y = 130
    if layers:
        body.append(rect(legend_x - 12, legend_y - 18, 232, 24 + 18 * len(layers[:8]), fill="white", stroke=INK_SOFT, stroke_width=0.5, opacity=0.9))
        body.append(text(legend_x, legend_y, "Layer stack (outer → inner)", size=11, fill=INK, weight="600"))
        for i, layer in enumerate(layers[:8]):
            yy = legend_y + 16 + i * 18
            hatch = (layer.get("hatch_key") or "").lower()
            swatch_fill = f"url(#hatch-{hatch})" if hatch in HATCH_PATTERNS else PAPER_DEEP
            body.append(rect(legend_x, yy - 10, 22, 14, fill=swatch_fill, stroke=INK_SOFT, stroke_width=0.4))
            body.append(text(legend_x + 28, yy, str(layer.get("label") or hatch or "—"), size=10, fill=INK))
            t_mm = layer.get("thickness_mm")
            if t_mm:
                body.append(text(legend_x + 200, yy, f"{float(t_mm):.0f} mm", size=9, fill=INK_SOFT, anchor="end"))

    # Scale bar lower-left.
    body.append(_scale_bar(40, canvas_h - 70, scale_label))

    svg = svg_open(canvas_w, canvas_h, title=sheet_title) + "".join(body) + svg_close()
    return {
        "id": "section_view",
        "name": "Section View",
        "format": "svg",
        "svg": svg,
        "meta": {
            "scale": scale_label,
            "cut_label": spec.get("cut_label") or "A-A",
            "view_target": spec.get("view_target"),
            "overall_height_mm": round(overall_h, 1),
            "overall_width_mm": round(overall_w, 1),
            "layer_count": len(layers),
            "joint_keys": joint_keys,
            "reinforcement_keys": reinf_keys,
            "back_angle_deg": back_angle_deg,
            "leg_taper_mm": leg_taper_mm if leg_taper_mm else None,
        },
    }
