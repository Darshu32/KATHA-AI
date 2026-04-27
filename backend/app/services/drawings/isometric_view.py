"""Isometric / perspective working drawing (BRD Layer 3A #4).

Axonometric (30°/30°) projection of a piece, drawn as a stack of
labelled boxes with material-finish hatches and optional exploded-view
offsets. Dimension chains for overall length × width × height are
superimposed on the iso axes; a legend lists the material finishes; a
scale bar + title block sit on the sheet edges.

Pure deterministic — the LLM-authored isometric_spec drives WHAT to
show; this module decides HOW to draw it.
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
    line,
    rect,
    svg_close,
    svg_open,
    text,
    title_block,
)
from app.services.diagrams.volumetric import (
    COS30,
    SIN30,
    _project as _iso_project,
)
from app.services.drawings.plan_view import (
    HATCH_PATTERNS,
    SCALE_OPTIONS,
    _hatch_defs,
    _scale_bar,
)

DEFAULT_SCALE = "1:10"
EXPLODE_GAP_PX = 4


def _mm(value: Any) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v * 1000.0 if 0 < v < 20 else v


def _box_iso(
    *,
    x_mm: float, y_mm: float, z_mm: float,
    length_mm: float, height_mm: float, depth_mm: float,
    scale_px_per_mm: float,
    ox: float, oy: float,
    fill_top: str, fill_left: str, fill_right: str,
    stroke: str = INK,
    stroke_width: float = 0.9,
) -> str:
    """Render a single iso box (top + left + right faces) at world coords (mm).

    World axes:
      x → length (long edge)
      y → height (vertical, up)
      z → depth  (short edge)
    """
    x_m = x_mm / 1000.0
    y_m = y_mm / 1000.0
    z_m = z_mm / 1000.0
    L = length_mm / 1000.0
    H = height_mm / 1000.0
    D = depth_mm / 1000.0

    # Eight corners → projected screen coords.
    p = lambda x, y, z: _iso_project(x, y, z, scale_px_per_mm * 1000.0, ox, oy)
    p000 = p(x_m,         y_m,         z_m)
    p100 = p(x_m + L,     y_m,         z_m)
    p010 = p(x_m,         y_m + H,     z_m)
    p110 = p(x_m + L,     y_m + H,     z_m)
    p001 = p(x_m,         y_m,         z_m + D)
    p101 = p(x_m + L,     y_m,         z_m + D)
    p011 = p(x_m,         y_m + H,     z_m + D)
    p111 = p(x_m + L,     y_m + H,     z_m + D)

    def _poly(points: list[tuple[float, float]], fill: str) -> str:
        pts = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
        return f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}"/>'

    parts: list[str] = []
    # Right face (positive x).
    parts.append(_poly([p100, p110, p111, p101], fill_right))
    # Left face (positive z).
    parts.append(_poly([p001, p011, p111, p101], fill_left))
    # Top face (positive y).
    parts.append(_poly([p010, p110, p111, p011], fill_top))
    return "".join(parts)


def _dim_iso(
    *,
    p1: tuple[float, float], p2: tuple[float, float],
    label: str,
    offset: tuple[float, float] = (0, -10),
) -> str:
    """Dimension line along an iso axis with arrowheads + label."""
    parts: list[str] = []
    parts.append(
        f'<line x1="{p1[0]:.2f}" y1="{p1[1]:.2f}" x2="{p2[0]:.2f}" y2="{p2[1]:.2f}" '
        f'stroke="{INK}" stroke-width="0.6" '
        f'marker-start="url(#dim-arrow)" marker-end="url(#dim-arrow)"/>'
    )
    cx = (p1[0] + p2[0]) / 2 + offset[0]
    cy = (p1[1] + p2[1]) / 2 + offset[1]
    parts.append(text(cx, cy, label, size=10, fill=INK, weight="600", anchor="middle"))
    return "".join(parts)


def _pick_scale(longest_edge_mm: float) -> str:
    if longest_edge_mm <= 1500:
        return "1:10"
    if longest_edge_mm <= 3000:
        return "1:20"
    return "1:50"


def render_isometric_view(
    *,
    piece: dict | None = None,
    isometric_spec: dict | None = None,
    canvas_w: int = 1200,
    canvas_h: int = 760,
    sheet_title: str = "Isometric View",
) -> dict:
    """Render the iso sheet from a piece envelope + LLM-authored isometric_spec.

    `piece` envelope (same as elevation/section path):
        { type, dimensions_mm, ergonomic_targets_mm, ... }

    `isometric_spec` (LLM-authored) carries:
        view_mode ("iso" | "perspective"), scale, parts[], explode_enabled,
        explode_factor (0..1.0), key_dimensions[], finishes_legend[],
        assembly_notes[].

    `parts[]` shape:
        { label, hatch_key, finish_label, color_hex,
          x_mm, y_mm, z_mm, length_mm, height_mm, depth_mm,
          explode_offset_mm: {x, y, z} (optional) }
    """
    spec = isometric_spec or {}
    piece = piece or {"type": "piece", "dimensions_mm": {"length": 800, "width": 800, "height": 750}}
    dims = piece.get("dimensions_mm") or {}
    overall_l = _mm(dims.get("length") or 800)
    overall_h = _mm(dims.get("height") or 750)
    overall_d = _mm(dims.get("width") or 800)

    scale_label = spec.get("scale") or DEFAULT_SCALE
    if scale_label not in SCALE_OPTIONS:
        scale_label = _pick_scale(max(overall_l, overall_h, overall_d))

    # Pixel scale — fit projected bbox into the available draw area.
    draw_w = canvas_w - 460
    draw_h = canvas_h - 220
    proj_w_m = (overall_l + overall_d) * COS30 / 1000.0  # iso footprint width in metres
    proj_h_m = ((overall_l + overall_d) * SIN30 + overall_h) / 1000.0
    explode_factor = float(spec.get("explode_factor") or 0.0)
    if spec.get("explode_enabled"):
        # Account for explode offsets in the bbox so nothing overflows.
        proj_w_m *= 1.0 + explode_factor * 0.6
        proj_h_m *= 1.0 + explode_factor * 0.6

    scale_px_per_m = min(draw_w / max(proj_w_m, 0.001), draw_h / max(proj_h_m, 0.001)) * 0.85
    scale_px_per_mm = scale_px_per_m / 1000.0
    ox = 80 + draw_w * 0.45
    oy = 110 + draw_h * 0.65

    body: list[str] = [
        background(canvas_w, canvas_h, fill=PAPER),
        _hatch_defs(),
        title_block(
            40, 36,
            sheet_title,
            f"{piece.get('type','piece').replace('_',' ').title()} — Isometric  |  Scale {scale_label}",
            width=canvas_w - 80,
        ),
    ]

    # Parts list — fall back to a single bounding box if the LLM didn't part it out.
    parts_in = spec.get("parts") or []
    if not parts_in:
        parts_in = [{
            "label": "overall",
            "hatch_key": piece.get("material_hatch_key") or "wood",
            "x_mm": 0, "y_mm": 0, "z_mm": 0,
            "length_mm": overall_l, "height_mm": overall_h, "depth_mm": overall_d,
        }]

    parts_drawn: list[dict[str, Any]] = []
    for i, part in enumerate(parts_in[:24]):
        x_mm = _mm(part.get("x_mm") or 0)
        y_mm = _mm(part.get("y_mm") or 0)
        z_mm = _mm(part.get("z_mm") or 0)
        L = _mm(part.get("length_mm") or 0) or 100
        H = _mm(part.get("height_mm") or 0) or 100
        D = _mm(part.get("depth_mm") or 0) or 100

        if spec.get("explode_enabled") and explode_factor > 0:
            off = part.get("explode_offset_mm") or {}
            x_mm += _mm(off.get("x") or 0) * explode_factor
            y_mm += _mm(off.get("y") or 0) * explode_factor
            z_mm += _mm(off.get("z") or 0) * explode_factor

        hatch = (part.get("hatch_key") or "").lower()
        # Three-tone face fills using the hatch + paper tones for shading.
        fill_top = f"url(#hatch-{hatch})" if hatch in HATCH_PATTERNS else PAPER_DEEP
        fill_left = PAPER_DEEP
        fill_right = "white"

        body.append(_box_iso(
            x_mm=x_mm, y_mm=y_mm, z_mm=z_mm,
            length_mm=L, height_mm=H, depth_mm=D,
            scale_px_per_mm=scale_px_per_mm,
            ox=ox, oy=oy,
            fill_top=fill_top, fill_left=fill_left, fill_right=fill_right,
        ))

        # Part label at front-top corner of the box.
        label_proj = _iso_project((x_mm + L) / 1000.0, (y_mm + H) / 1000.0, z_mm / 1000.0,
                                  scale_px_per_mm * 1000.0, ox, oy)
        body.append(text(label_proj[0] + 4, label_proj[1] - 4, str(part.get("label") or f"P{i+1}"), size=9, fill=INK_SOFT))

        parts_drawn.append({"label": part.get("label"), "hatch_key": hatch})

    # Overall dimension chains along iso axes (skip if exploded — gets noisy).
    if not spec.get("explode_enabled"):
        # Length axis: bottom-front edge.
        p_l1 = _iso_project(0,            0, 0,            scale_px_per_mm * 1000.0, ox, oy)
        p_l2 = _iso_project(overall_l/1000.0, 0, 0,        scale_px_per_mm * 1000.0, ox, oy)
        body.append(_dim_iso(p1=(p_l1[0], p_l1[1] + 22), p2=(p_l2[0], p_l2[1] + 22),
                             label=f"L {overall_l:.0f}", offset=(0, 14)))
        # Depth axis: bottom-side edge.
        p_d1 = _iso_project(0,            0, 0,            scale_px_per_mm * 1000.0, ox, oy)
        p_d2 = _iso_project(0,            0, overall_d/1000.0, scale_px_per_mm * 1000.0, ox, oy)
        body.append(_dim_iso(p1=(p_d1[0] - 22, p_d1[1] + 14), p2=(p_d2[0] - 22, p_d2[1] + 14),
                             label=f"D {overall_d:.0f}", offset=(-30, 0)))
        # Height axis: front-vertical edge.
        p_h1 = _iso_project(overall_l/1000.0, 0,            0, scale_px_per_mm * 1000.0, ox, oy)
        p_h2 = _iso_project(overall_l/1000.0, overall_h/1000.0, 0, scale_px_per_mm * 1000.0, ox, oy)
        body.append(_dim_iso(p1=(p_h1[0] + 22, p_h1[1]), p2=(p_h2[0] + 22, p_h2[1]),
                             label=f"H {overall_h:.0f}", offset=(28, 0)))

    # Right-side legend — material finishes.
    legend_x = canvas_w - 240
    legend_y = 130
    finishes = spec.get("finishes_legend") or []
    if finishes:
        body.append(rect(legend_x - 12, legend_y - 18, 232, 24 + 22 * len(finishes[:8]),
                         fill="white", stroke=INK_SOFT, stroke_width=0.5, opacity=0.92))
        body.append(text(legend_x, legend_y, "Material finishes", size=11, fill=INK, weight="600"))
        for i, f in enumerate(finishes[:8]):
            yy = legend_y + 16 + i * 22
            hatch = (f.get("hatch_key") or "").lower()
            swatch_fill = f"url(#hatch-{hatch})" if hatch in HATCH_PATTERNS else PAPER_DEEP
            body.append(rect(legend_x, yy - 12, 22, 16, fill=swatch_fill, stroke=INK_SOFT, stroke_width=0.4))
            color_hex = f.get("color_hex")
            if color_hex:
                body.append(rect(legend_x + 26, yy - 12, 16, 16, fill=color_hex, stroke=INK_SOFT, stroke_width=0.4))
                body.append(text(legend_x + 50, yy, f"{f.get('finish_label') or hatch}  ({color_hex})", size=9, fill=INK))
            else:
                body.append(text(legend_x + 30, yy, str(f.get("finish_label") or hatch), size=10, fill=INK))

    # Assembly notes panel below the legend.
    notes = spec.get("assembly_notes") or []
    if notes:
        notes_y = legend_y + 30 + 22 * min(len(finishes), 8) + 24
        body.append(text(legend_x, notes_y, "Assembly notes", size=11, fill=INK, weight="600"))
        for i, n in enumerate(notes[:5]):
            body.append(text(legend_x, notes_y + 16 + i * 14, "• " + str(n), size=9, fill=INK_SOFT))

    # Scale bar lower-left.
    body.append(_scale_bar(40, canvas_h - 70, scale_label))

    # Explode marker — small chip on the title bar so the viewer knows.
    if spec.get("explode_enabled"):
        body.append(rect(canvas_w - 130, 40, 88, 22, fill=ACCENT_WARM, stroke=INK, stroke_width=0.7))
        body.append(text(canvas_w - 86, 55, f"EXPLODED ×{explode_factor:.1f}", size=10, fill="white", weight="700", anchor="middle"))

    svg = svg_open(canvas_w, canvas_h, title=sheet_title) + "".join(body) + svg_close()
    return {
        "id": "isometric_view",
        "name": "Isometric View",
        "format": "svg",
        "svg": svg,
        "meta": {
            "scale": scale_label,
            "view_mode": spec.get("view_mode") or "iso",
            "overall_length_mm": round(overall_l, 1),
            "overall_height_mm": round(overall_h, 1),
            "overall_depth_mm": round(overall_d, 1),
            "part_count": len(parts_drawn),
            "explode_enabled": bool(spec.get("explode_enabled")),
            "explode_factor": explode_factor,
            "finishes_count": len(finishes),
        },
    }
