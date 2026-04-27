"""Detail sheet renderer (BRD Layer 3A #5).

A multi-cell detail sheet — 4 to 9 zoomed-in details on one page, each
showing a joint, a hardware interface, an edge treatment, a seam, or a
material transition. Each cell carries its own title, scale stamp,
diagrammatic sketch, dimension callouts, and short notes.

The cell sketches are intentionally schematic (not photoreal) so they
read as construction drawings, not renders. The LLM-authored detail_spec
drives WHAT each cell shows; this module decides HOW to draw it.
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
from app.services.drawings.plan_view import (
    HATCH_PATTERNS,
    _hatch_defs,
)

# Catalogue of detail types the LLM picks from.
DETAIL_TYPES = (
    "joint",                # mortise-tenon, dovetail, pocket-hole, dowel
    "hardware",             # mounting / assembly interface
    "edge_treatment",       # chamfer / round-over / bevel
    "seam_stitching",       # upholstery seam / piping
    "material_transition",  # wood→metal, foam→fabric edge, etc.
)

# Per-cell scale options — tighter than working-drawing catalogue.
DETAIL_SCALE_OPTIONS = ("1:1", "1:2", "1:5", "1:10")

JOINT_SUBTYPES = ("mortise_tenon", "dovetail", "pocket_hole", "dowel", "biscuit", "finger_joint")
EDGE_PROFILES = ("square", "chamfer_45", "round_over", "ogee", "bevel", "bullnose")
SEAM_TYPES = ("plain", "piping", "double_topstitch", "blind_stitch", "french_seam")


def _cell_frame(x: float, y: float, w: float, h: float, title: str, scale: str, key: str) -> list[str]:
    """Render the per-cell envelope: outline, title bar, scale stamp, key bubble."""
    parts: list[str] = []
    parts.append(rect(x, y, w, h, fill="white", stroke=INK, stroke_width=0.9))
    # Title strip on top.
    parts.append(rect(x, y, w, 22, fill=PAPER_DEEP, stroke="none"))
    parts.append(text(x + 8, y + 15, title, size=10, fill=INK, weight="700"))
    # Scale stamp on top-right.
    parts.append(text(x + w - 8, y + 15, f"Scale {scale}", size=9, fill=INK_SOFT, weight="600", anchor="end"))
    # Key bubble on top-left circle.
    parts.append(circle(x + 14, y + 12, 11, fill=PAPER))
    parts.append(
        f'<circle cx="{x + 14:.2f}" cy="{y + 12:.2f}" r="11" fill="none" '
        f'stroke="{INK}" stroke-width="0.7"/>'
    )
    parts.append(text(x + 14, y + 15, key, size=10, fill=INK, anchor="middle", weight="700"))
    return parts


def _draw_dimension(x1: float, y1: float, x2: float, y2: float, label: str) -> str:
    """Tiny dim chain for a detail cell."""
    return (
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
        f'stroke="{INK}" stroke-width="0.5" '
        f'marker-start="url(#dim-arrow)" marker-end="url(#dim-arrow)"/>'
        f'{text((x1 + x2) / 2, (y1 + y2) / 2 - 3, label, size=8, fill=INK, weight="600", anchor="middle")}'
    )


def _draw_joint_cell(
    x: float, y: float, w: float, h: float, *,
    subtype: str,
    members: list[str] | None = None,
    tolerance_mm: float | None = None,
) -> list[str]:
    """Schematic cross-section of a joinery detail."""
    parts: list[str] = []
    inset_x = x + 30
    inset_y = y + 40
    inset_w = w - 60
    inset_h = h - 80

    if subtype == "mortise_tenon":
        # Two members meeting at a right angle: vertical leg + horizontal apron.
        leg_w = inset_w * 0.18
        apron_h = inset_h * 0.30
        cy = inset_y + inset_h / 2
        # Vertical leg.
        parts.append(rect(inset_x + inset_w * 0.30, inset_y + 6, leg_w, inset_h - 12, fill="url(#hatch-wood)", stroke=INK, stroke_width=0.8))
        # Horizontal apron with hidden tenon outline.
        parts.append(rect(inset_x + inset_w * 0.30 + leg_w, cy - apron_h / 2, inset_w * 0.45, apron_h, fill="url(#hatch-wood)", stroke=INK, stroke_width=0.8))
        # Tenon hidden inside leg (dashed — inline rect since svg_base.rect has no dash).
        ten_x = inset_x + inset_w * 0.30
        ten_y = cy - apron_h * 0.35
        ten_w = leg_w
        ten_h = apron_h * 0.7
        parts.append(
            f'<rect x="{ten_x:.2f}" y="{ten_y:.2f}" width="{ten_w:.2f}" height="{ten_h:.2f}" '
            f'fill="none" stroke="{INK}" stroke-width="0.6" stroke-dasharray="3 2"/>'
        )
        # Mortise label.
        parts.append(text(inset_x + inset_w * 0.30 + leg_w / 2, cy - apron_h / 2 - 6, "mortise", size=8, fill=INK_SOFT, anchor="middle"))
        parts.append(text(inset_x + inset_w * 0.55, cy + apron_h / 2 + 12, "tenon (hidden)", size=8, fill=INK_SOFT, anchor="middle"))
    elif subtype == "dovetail":
        # Schematic dovetail joint — pin-tail trapezoids.
        bx = inset_x + inset_w * 0.20
        by = inset_y + inset_h * 0.30
        bw = inset_w * 0.55
        bh = inset_h * 0.40
        parts.append(rect(bx, by, bw, bh, fill="url(#hatch-wood)", stroke=INK, stroke_width=0.8))
        # Three trapezoids to suggest dovetails.
        for i in range(3):
            tx_left = bx + bw * (0.1 + i * 0.30)
            tw = bw * 0.18
            taper = 6
            parts.append(
                f'<polygon points="{tx_left:.2f},{by:.2f} {tx_left + tw:.2f},{by:.2f} '
                f'{tx_left + tw - taper:.2f},{by + bh:.2f} {tx_left + taper:.2f},{by + bh:.2f}" '
                f'fill="white" stroke="{INK}" stroke-width="0.7"/>'
            )
        parts.append(text(bx + bw / 2, by - 6, "pins / tails", size=8, fill=INK_SOFT, anchor="middle"))
    elif subtype in {"pocket_hole", "dowel", "biscuit"}:
        # Two boards meeting with internal fasteners shown as circles or dashed cylinders.
        bx = inset_x + 12
        by = inset_y + inset_h / 2 - inset_h * 0.18
        bh = inset_h * 0.36
        bw = inset_w - 24
        # Top board.
        parts.append(rect(bx, by, bw / 2, bh, fill="url(#hatch-wood)", stroke=INK, stroke_width=0.8))
        # Bottom board (offset down).
        parts.append(rect(bx + bw / 2, by + 4, bw / 2, bh, fill="url(#hatch-wood)", stroke=INK, stroke_width=0.8))
        # Fastener marks.
        for i in range(2):
            cx = bx + bw * (0.40 + i * 0.10)
            cy = by + bh / 2
            if subtype == "pocket_hole":
                parts.append(line(cx - 6, cy - 6, cx + 6, cy + 6, stroke=INK, stroke_width=0.7))
            elif subtype == "dowel":
                parts.append(circle(cx, cy, 3, fill=ACCENT_WARM))
                parts.append(line(cx - 8, cy, cx + 8, cy, stroke=INK, stroke_width=0.5, dash="2 2"))
            else:  # biscuit
                parts.append(
                    f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="6" ry="2" fill="{ACCENT_COOL}" stroke="{INK}" stroke-width="0.5"/>'
                )
        parts.append(text(bx + bw / 2, by - 6, subtype.replace("_", " "), size=8, fill=INK_SOFT, anchor="middle"))
    else:
        # Generic joint placeholder.
        parts.append(text(inset_x + inset_w / 2, inset_y + inset_h / 2,
                          subtype.replace("_", " "), size=10, fill=INK_SOFT, anchor="middle"))

    if members:
        parts.append(text(x + 8, y + h - 18, "Members: " + ", ".join(members), size=8, fill=INK_SOFT))
    if tolerance_mm is not None:
        parts.append(text(x + w - 8, y + h - 18, f"±{tolerance_mm:.1f} mm", size=8, fill=INK_SOFT, anchor="end"))
    return parts


def _draw_hardware_cell(
    x: float, y: float, w: float, h: float, *,
    hardware_type: str,
    mounting: str,
    fastener: str | None = None,
) -> list[str]:
    """Schematic mounting/interface for a hardware piece."""
    parts: list[str] = []
    inset_x = x + 30
    inset_y = y + 40
    inset_w = w - 60
    inset_h = h - 80
    # Substrate.
    sub_h = inset_h * 0.45
    parts.append(rect(inset_x, inset_y + sub_h * 0.3, inset_w, sub_h, fill="url(#hatch-wood)", stroke=INK, stroke_width=0.8))
    # Hardware piece on top.
    hw_w = inset_w * 0.30
    hw_h = inset_h * 0.20
    hx = inset_x + inset_w / 2 - hw_w / 2
    hy = inset_y + sub_h * 0.3 - hw_h
    parts.append(rect(hx, hy, hw_w, hw_h, fill="url(#hatch-metal)", stroke=INK, stroke_width=0.8))
    parts.append(text(hx + hw_w / 2, hy - 4, hardware_type, size=9, fill=INK, anchor="middle", weight="600"))
    # Fasteners — two screws through hardware into substrate.
    for i in (0.30, 0.70):
        sx = hx + hw_w * i
        sy_top = hy + 2
        sy_bot = inset_y + sub_h * 0.3 + sub_h * 0.6
        parts.append(line(sx, sy_top, sx, sy_bot, stroke=INK, stroke_width=1.0))
        parts.append(circle(sx, sy_top, 2, fill=INK))
    parts.append(text(inset_x, inset_y + sub_h + 18, f"Mounting: {mounting}", size=8, fill=INK_SOFT))
    if fastener:
        parts.append(text(inset_x, inset_y + sub_h + 30, f"Fastener: {fastener}", size=8, fill=INK_SOFT))
    return parts


def _draw_edge_cell(
    x: float, y: float, w: float, h: float, *,
    profile: str,
    radius_mm: float | None = None,
) -> list[str]:
    """Schematic edge profile cross-section."""
    parts: list[str] = []
    inset_x = x + 30
    inset_y = y + 50
    inset_w = w - 60
    inset_h = h - 90
    # Board cross-section.
    board_w = inset_w * 0.8
    board_h = inset_h * 0.4
    bx = inset_x + (inset_w - board_w) / 2
    by = inset_y + (inset_h - board_h) / 2
    if profile == "square":
        parts.append(rect(bx, by, board_w, board_h, fill="url(#hatch-wood)", stroke=INK, stroke_width=1.0))
    elif profile == "chamfer_45":
        chamf = min(board_h * 0.45, board_w * 0.10)
        pts = [
            (bx + chamf, by), (bx + board_w - chamf, by),
            (bx + board_w, by + chamf), (bx + board_w, by + board_h - chamf),
            (bx + board_w - chamf, by + board_h), (bx + chamf, by + board_h),
            (bx, by + board_h - chamf), (bx, by + chamf),
        ]
        parts.append(f'<polygon points="{" ".join(f"{px:.2f},{py:.2f}" for px,py in pts)}" '
                     f'fill="url(#hatch-wood)" stroke="{INK}" stroke-width="1.0"/>')
    elif profile in {"round_over", "bullnose"}:
        r = board_h * 0.5 if profile == "bullnose" else board_h * 0.4
        path = (
            f'<path d="M {bx} {by} L {bx + board_w - r} {by} '
            f'A {r} {r} 0 0 1 {bx + board_w} {by + r} '
            f'L {bx + board_w} {by + board_h - r} '
            f'A {r} {r} 0 0 1 {bx + board_w - r} {by + board_h} '
            f'L {bx} {by + board_h} Z" '
            f'fill="url(#hatch-wood)" stroke="{INK}" stroke-width="1.0"/>'
        )
        parts.append(path)
    elif profile in {"ogee", "bevel"}:
        # Simplified ogee — board with sloped right edge.
        slope = board_w * 0.18
        pts = [
            (bx, by), (bx + board_w - slope, by),
            (bx + board_w, by + board_h * 0.5),
            (bx + board_w - slope, by + board_h),
            (bx, by + board_h),
        ]
        parts.append(f'<polygon points="{" ".join(f"{px:.2f},{py:.2f}" for px,py in pts)}" '
                     f'fill="url(#hatch-wood)" stroke="{INK}" stroke-width="1.0"/>')
    else:
        parts.append(rect(bx, by, board_w, board_h, fill="url(#hatch-wood)", stroke=INK, stroke_width=1.0))

    # Profile label + radius.
    parts.append(text(inset_x, inset_y + inset_h + 14, f"Profile: {profile.replace('_', ' ')}", size=9, fill=INK_SOFT))
    if radius_mm is not None:
        parts.append(text(inset_x + inset_w, inset_y + inset_h + 14, f"R = {radius_mm:.1f} mm", size=9, fill=INK_SOFT, anchor="end"))
    return parts


def _draw_seam_cell(
    x: float, y: float, w: float, h: float, *,
    seam_type: str,
    stitch_density_per_inch: float | None = None,
) -> list[str]:
    """Schematic upholstery seam diagram."""
    parts: list[str] = []
    inset_x = x + 30
    inset_y = y + 50
    inset_w = w - 60
    inset_h = h - 90
    cy = inset_y + inset_h * 0.45

    # Two fabric layers meeting at the seam.
    parts.append(rect(inset_x, cy - inset_h * 0.30, inset_w * 0.45, inset_h * 0.30, fill="url(#hatch-fabric)", stroke=INK, stroke_width=0.7))
    parts.append(rect(inset_x + inset_w * 0.55, cy - inset_h * 0.30, inset_w * 0.45, inset_h * 0.30, fill="url(#hatch-fabric)", stroke=INK, stroke_width=0.7))

    # Seam line (vertical at centre).
    seam_x = inset_x + inset_w / 2
    parts.append(line(seam_x, cy - inset_h * 0.32, seam_x, cy + inset_h * 0.05, stroke=INK, stroke_width=1.0))

    # Stitches.
    if seam_type in {"plain", "double_topstitch", "blind_stitch", "french_seam"}:
        rows = 2 if seam_type == "double_topstitch" else 1
        for r in range(rows):
            row_x = seam_x + (-6 if r == 0 else 6)
            for i in range(8):
                yy = cy - inset_h * 0.30 + i * (inset_h * 0.04)
                parts.append(line(row_x - 2, yy, row_x + 2, yy, stroke=INK, stroke_width=0.7))
    elif seam_type == "piping":
        # Piping bead beside the seam.
        parts.append(circle(seam_x, cy - inset_h * 0.05, 4, fill=ACCENT_WARM))
        parts.append(text(seam_x + 12, cy - inset_h * 0.05, "piping cord", size=8, fill=INK_SOFT))

    parts.append(text(inset_x, inset_y + inset_h + 14, f"Seam: {seam_type.replace('_', ' ')}", size=9, fill=INK_SOFT))
    if stitch_density_per_inch is not None:
        parts.append(text(inset_x + inset_w, inset_y + inset_h + 14,
                          f"{stitch_density_per_inch:.0f} stitches / inch", size=9, fill=INK_SOFT, anchor="end"))
    return parts


def _draw_transition_cell(
    x: float, y: float, w: float, h: float, *,
    from_material: str, to_material: str,
    detail: str | None = None,
) -> list[str]:
    """Schematic material-transition junction."""
    parts: list[str] = []
    inset_x = x + 30
    inset_y = y + 50
    inset_w = w - 60
    inset_h = h - 90
    half_w = inset_w * 0.45
    band_h = inset_h * 0.55
    by = inset_y + (inset_h - band_h) / 2

    from_hatch = (from_material or "").lower()
    to_hatch = (to_material or "").lower()
    fill_from = f"url(#hatch-{from_hatch})" if from_hatch in HATCH_PATTERNS else PAPER_DEEP
    fill_to = f"url(#hatch-{to_hatch})" if to_hatch in HATCH_PATTERNS else PAPER_DEEP

    parts.append(rect(inset_x, by, half_w, band_h, fill=fill_from, stroke=INK, stroke_width=0.8))
    parts.append(rect(inset_x + inset_w - half_w, by, half_w, band_h, fill=fill_to, stroke=INK, stroke_width=0.8))

    # Junction line / shadow gap (dashed — inline since svg_base.rect has no dash).
    j_x_left = inset_x + half_w
    j_x_right = inset_x + inset_w - half_w
    parts.append(
        f'<rect x="{j_x_left:.2f}" y="{by:.2f}" width="{j_x_right - j_x_left:.2f}" height="{band_h:.2f}" '
        f'fill="{PAPER}" stroke="{INK_SOFT}" stroke-width="0.5" stroke-dasharray="4 2"/>'
    )

    parts.append(text(inset_x + half_w / 2, by - 6, from_material, size=9, fill=INK_SOFT, anchor="middle"))
    parts.append(text(inset_x + inset_w - half_w / 2, by - 6, to_material, size=9, fill=INK_SOFT, anchor="middle"))
    parts.append(text(inset_x + inset_w / 2, by + band_h + 14,
                      detail or "junction", size=9, fill=INK, anchor="middle", weight="600"))
    return parts


def _draw_cell(
    x: float, y: float, w: float, h: float, *, cell: dict[str, Any], key: str,
) -> list[str]:
    title = cell.get("title") or cell.get("detail_type", "Detail").replace("_", " ").title()
    scale = cell.get("scale") or "1:5"
    parts = _cell_frame(x, y, w, h, title, scale, key)
    dt = (cell.get("detail_type") or "").lower()
    if dt == "joint":
        parts.extend(_draw_joint_cell(
            x, y, w, h,
            subtype=(cell.get("subtype") or "mortise_tenon"),
            members=cell.get("members"),
            tolerance_mm=cell.get("tolerance_mm"),
        ))
    elif dt == "hardware":
        parts.extend(_draw_hardware_cell(
            x, y, w, h,
            hardware_type=(cell.get("hardware_type") or "bracket"),
            mounting=(cell.get("mounting") or "screw"),
            fastener=cell.get("fastener"),
        ))
    elif dt == "edge_treatment":
        parts.extend(_draw_edge_cell(
            x, y, w, h,
            profile=(cell.get("profile") or "round_over"),
            radius_mm=cell.get("radius_mm"),
        ))
    elif dt == "seam_stitching":
        parts.extend(_draw_seam_cell(
            x, y, w, h,
            seam_type=(cell.get("seam_type") or "plain"),
            stitch_density_per_inch=cell.get("stitch_density_per_inch"),
        ))
    elif dt == "material_transition":
        parts.extend(_draw_transition_cell(
            x, y, w, h,
            from_material=(cell.get("from_material") or "wood"),
            to_material=(cell.get("to_material") or "metal"),
            detail=cell.get("transition_detail"),
        ))
    else:
        parts.append(text(x + w / 2, y + h / 2, "(no template for type)", size=10, fill=INK_MUTED, anchor="middle"))

    # Cell footnote — short notes.
    note = cell.get("note")
    if note:
        parts.append(text(x + 8, y + h - 6, note[:90], size=8, fill=INK_MUTED))
    return parts


def render_detail_sheet(
    *,
    detail_spec: dict | None = None,
    canvas_w: int = 1200,
    canvas_h: int = 820,
    sheet_title: str = "Detail Sheet",
) -> dict:
    """Render the detail sheet from an LLM-authored detail_spec.

    detail_spec carries:
        sheet_narrative, columns (2|3), cells[] each with detail_type +
        per-type fields, scale per cell.
    """
    spec = detail_spec or {}
    cells = spec.get("cells") or []
    columns = int(spec.get("columns") or (3 if len(cells) > 4 else 2))
    columns = max(1, min(columns, 3))

    body: list[str] = [
        background(canvas_w, canvas_h, fill=PAPER),
        _hatch_defs(),
        title_block(
            40, 36,
            sheet_title,
            f"Detail sheet — {len(cells)} cell(s)",
            width=canvas_w - 80,
        ),
    ]

    if not cells:
        body.append(text(canvas_w / 2, canvas_h / 2, "(no cells supplied)", size=12, fill=INK_MUTED, anchor="middle"))
        svg = svg_open(canvas_w, canvas_h, title=sheet_title) + "".join(body) + svg_close()
        return {"id": "detail_sheet", "name": "Detail Sheet", "format": "svg", "svg": svg, "meta": {"cell_count": 0}}

    # Grid layout.
    grid_x = 40
    grid_y = 100
    grid_w = canvas_w - 80
    grid_h = canvas_h - 160
    rows = (len(cells) + columns - 1) // columns
    cell_w = (grid_w - (columns - 1) * 12) / columns
    cell_h = (grid_h - (rows - 1) * 12) / rows

    detail_keys: list[str] = []
    for i, cell in enumerate(cells[:9]):
        col = i % columns
        row = i // columns
        cx = grid_x + col * (cell_w + 12)
        cy = grid_y + row * (cell_h + 12)
        key = (cell.get("key") or f"D{i+1}").upper()
        body.extend(_draw_cell(cx, cy, cell_w, cell_h, cell=cell, key=key))
        detail_keys.append(key)

    # Footer narrative.
    narrative = (spec.get("sheet_narrative") or "").strip()
    if narrative:
        body.append(text(40, canvas_h - 24, narrative[:160], size=10, fill=INK_SOFT))

    svg = svg_open(canvas_w, canvas_h, title=sheet_title) + "".join(body) + svg_close()
    return {
        "id": "detail_sheet",
        "name": "Detail Sheet",
        "format": "svg",
        "svg": svg,
        "meta": {
            "cell_count": len(cells),
            "columns": columns,
            "rows": rows,
            "detail_keys": detail_keys,
            "detail_types": [c.get("detail_type") for c in cells],
        },
    }
