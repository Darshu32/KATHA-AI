"""G-code exporter — RS-274 toolpath for CNC routing (BRD Layer 5A).

Per BRD: NC / G-code with CNC machining instructions, routing patterns
for wood, nesting optimisation, and tool specifications.

Emitted programs (concatenated into a single file with explicit tool
changes):

    T1 — 6 mm flat end mill: contour cut around each footprint
    T2 — 3 mm flat end mill: rebate / dado routing pattern (wood)
    T3 — 4 mm twist drill:    pilot holes for hardware (corner mounts)

Sheet nesting is performed first (left-to-right shelf packing on a
1220 × 2440 mm panel); every footprint is laid out on the sheet
*before* any G-code is emitted, and the tool paths walk the nested
positions, not the original world coordinates.

Conventions:
    G21 (mm), G90 (absolute), G17 (XY plane), G54 (WCS).
    Z safe = 5 mm. Cut depth defaults from sheet thickness (18 mm).
"""

from __future__ import annotations

from datetime import datetime, timezone


# ── Tool catalogue (stamped into the file header for the CNC operator) ──────
TOOLS: list[dict] = [
    {"slot": "T1", "name": "6mm flat end mill",  "diameter_mm": 6.0,
     "flutes": 2, "rpm": 18000, "feed_mm_min": 1200, "plunge_mm_min": 400,
     "use": "contour cut"},
    {"slot": "T2", "name": "3mm flat end mill",  "diameter_mm": 3.0,
     "flutes": 2, "rpm": 22000, "feed_mm_min":  900, "plunge_mm_min": 300,
     "use": "rebate / dado routing"},
    {"slot": "T3", "name": "4mm twist drill",    "diameter_mm": 4.0,
     "flutes": 2, "rpm": 12000, "feed_mm_min":  300, "plunge_mm_min": 150,
     "use": "hardware pilot holes"},
]

# Stock sheet (mm) — generic hardwood ply panel.
SHEET_W_MM = 1220.0
SHEET_H_MM = 2440.0
SHEET_KERF_MM = 8.0          # gap between parts
SHEET_THICKNESS_MM = 18.0


def _m_to_mm(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 20 else v * 1000.0


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "project")).strip("-") or "project"


# ── Nesting (shelf / left-to-right packing) ─────────────────────────────────


def _nest_parts(parts: list[dict], *, sheet_w: float = SHEET_W_MM,
                sheet_h: float = SHEET_H_MM, kerf: float = SHEET_KERF_MM
                ) -> list[dict]:
    """Place each part top-down using shelf packing. Yields nested coords."""
    sorted_parts = sorted(parts, key=lambda p: -p["height_mm"])
    cursor_x, cursor_y, shelf_h = 0.0, 0.0, 0.0
    placed: list[dict] = []
    for p in sorted_parts:
        w, h = p["width_mm"], p["height_mm"]
        if w + kerf > sheet_w:
            # Skip oversize parts (caller can split into sub-panels later).
            placed.append({**p, "placed": False, "reason": "exceeds sheet width"})
            continue
        if cursor_x + w + kerf > sheet_w:
            cursor_x = 0.0
            cursor_y += shelf_h + kerf
            shelf_h = 0.0
        if cursor_y + h + kerf > sheet_h:
            placed.append({**p, "placed": False, "reason": "sheet full"})
            continue
        placed.append({
            **p,
            "placed": True,
            "x_mm": cursor_x,
            "y_mm": cursor_y,
            "x2_mm": cursor_x + w,
            "y2_mm": cursor_y + h,
        })
        cursor_x += w + kerf
        shelf_h = max(shelf_h, h)
    return placed


def _utilisation(parts: list[dict], *, sheet_w: float = SHEET_W_MM,
                 sheet_h: float = SHEET_H_MM) -> float:
    used = sum(p["width_mm"] * p["height_mm"] for p in parts if p.get("placed"))
    return round(used / (sheet_w * sheet_h) * 100, 1) if sheet_w * sheet_h else 0.0


# ── G-code emitters ─────────────────────────────────────────────────────────


def _header(project_name: str, sheet_thickness_mm: float) -> list[str]:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = [
        "; KATHA AI — CNC routing program",
        f"; project: {project_name}",
        f"; generated: {ts}",
        f"; stock: hardwood ply {SHEET_W_MM:.0f} x {SHEET_H_MM:.0f} x {sheet_thickness_mm:.0f} mm",
        f"; kerf gap: {SHEET_KERF_MM:.0f} mm",
        "; tool catalogue:",
    ]
    for t in TOOLS:
        out.append(
            f";   {t['slot']}: {t['name']:24s}  rpm {t['rpm']:>5d}  feed {t['feed_mm_min']:>4d}  plunge {t['plunge_mm_min']:>3d}  use: {t['use']}"
        )
    out += [
        "",
        "G21",     # mm
        "G90",     # absolute
        "G17",     # XY plane
        "G54",     # work coordinate system
    ]
    return out


def _spindle_on(rpm: int) -> list[str]:
    return [f"M3 S{rpm}"]


def _spindle_off() -> list[str]:
    return ["M5"]


def _tool_change(tool: dict, safe_z: float) -> list[str]:
    return [
        "",
        f"; --- TOOL CHANGE → {tool['slot']} {tool['name']} ({tool['use']}) ---",
        f"M5",
        f"G0 Z{safe_z * 2:.2f}",
        f"M6 {tool['slot']}",
        f"M3 S{tool['rpm']}",
        f"G4 P2",                # 2-second dwell after spindle up
    ]


def _contour(part: dict, *, tool_r: float, depth_mm: float, step_mm: float,
             feed: int, plunge: int, safe_z: float) -> list[str]:
    """T1 — outline the footprint so the part falls free of the sheet."""
    x1 = part["x_mm"] - tool_r
    y1 = part["y_mm"] - tool_r
    x2 = part["x2_mm"] + tool_r
    y2 = part["y2_mm"] + tool_r
    out = [
        "",
        f"; contour {part['id']} ({part['width_mm']:.1f} x {part['height_mm']:.1f} mm)",
        f"G0 X{x1:.2f} Y{y1:.2f}",
        f"G0 Z{safe_z:.2f}",
    ]
    z = 0.0
    while z > -depth_mm + 1e-6:
        z = max(z - step_mm, -depth_mm)
        out.append(f"G1 Z{z:.2f} F{plunge}")
        out += [
            f"G1 X{x2:.2f} Y{y1:.2f} F{feed}",
            f"G1 X{x2:.2f} Y{y2:.2f}",
            f"G1 X{x1:.2f} Y{y2:.2f}",
            f"G1 X{x1:.2f} Y{y1:.2f}",
        ]
    out.append(f"G0 Z{safe_z:.2f}")
    return out


def _rebate(part: dict, *, depth_mm: float, feed: int, plunge: int,
            safe_z: float) -> list[str]:
    """T2 — single perimeter rebate 30 mm in from the edge (back-panel slot)."""
    inset = 30.0
    x1 = part["x_mm"] + inset
    y1 = part["y_mm"] + inset
    x2 = part["x2_mm"] - inset
    y2 = part["y2_mm"] - inset
    if x2 - x1 < 50 or y2 - y1 < 50:
        return [f"; rebate skipped on {part['id']} — part too small for inset 30 mm"]
    return [
        "",
        f"; rebate {part['id']} (perimeter dado, depth {depth_mm:.1f} mm)",
        f"G0 X{x1:.2f} Y{y1:.2f}",
        f"G0 Z{safe_z:.2f}",
        f"G1 Z{-depth_mm:.2f} F{plunge}",
        f"G1 X{x2:.2f} Y{y1:.2f} F{feed}",
        f"G1 X{x2:.2f} Y{y2:.2f}",
        f"G1 X{x1:.2f} Y{y2:.2f}",
        f"G1 X{x1:.2f} Y{y1:.2f}",
        f"G0 Z{safe_z:.2f}",
    ]


def _pilot_holes(part: dict, *, depth_mm: float, feed: int, plunge: int,
                 safe_z: float) -> list[str]:
    """T3 — 4 corner pilot holes for hardware (50 mm in from each corner)."""
    inset = 50.0
    cx1 = part["x_mm"] + inset
    cy1 = part["y_mm"] + inset
    cx2 = part["x2_mm"] - inset
    cy2 = part["y2_mm"] - inset
    if cx2 - cx1 < 50 or cy2 - cy1 < 50:
        return [f"; pilot holes skipped on {part['id']} — part too small"]
    out: list[str] = ["", f"; pilot holes {part['id']} (4 corners, ø4 mm × {depth_mm:.1f} mm)"]
    for x, y in ((cx1, cy1), (cx2, cy1), (cx2, cy2), (cx1, cy2)):
        out += [
            f"G0 X{x:.2f} Y{y:.2f}",
            f"G0 Z{safe_z:.2f}",
            f"G1 Z{-depth_mm:.2f} F{plunge}",
            f"G0 Z{safe_z:.2f}",
        ]
    return out


# ── Public ──────────────────────────────────────────────────────────────────


FURNITURE_TYPES = frozenset({
    "sofa", "chair", "dining_chair", "lounge_chair", "office_chair",
    "dining_table", "coffee_table", "desk", "console_table", "side_table",
    "bed", "bookshelf", "wardrobe", "cabinet", "tv_unit", "media_console",
})


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta", {})
    project_name = meta.get("project_name") or "KATHA Project"
    safe_z = 5.0
    sheet_thickness = float(meta.get("sheet_thickness_mm", SHEET_THICKNESS_MM))
    contour_depth = sheet_thickness + 1.0          # cut clean through stock + 1 mm
    rebate_depth = max(sheet_thickness / 3, 4.0)
    pilot_depth = max(sheet_thickness * 0.6, 8.0)

    # Pull furniture footprints from the graph.
    parts: list[dict] = []
    for obj in graph.get("objects") or []:
        otype = (obj.get("type") or "").lower()
        if otype not in FURNITURE_TYPES:
            continue
        d = obj.get("dimensions") or {}
        l = max(_m_to_mm(d.get("length")) or 400.0, 50.0)
        w = max(_m_to_mm(d.get("width")) or 400.0, 50.0)
        parts.append({
            "id": obj.get("id") or otype,
            "type": otype,
            "width_mm": l,
            "height_mm": w,
        })

    nested = _nest_parts(parts)
    placed = [p for p in nested if p.get("placed")]
    unplaced = [p for p in nested if not p.get("placed")]
    util = _utilisation(nested)

    lines: list[str] = _header(project_name, sheet_thickness)

    # Nesting summary in the file header.
    lines += [
        "",
        f"; nesting summary: {len(placed)} placed / {len(unplaced)} unplaced; "
        f"sheet utilisation {util:.1f} %",
    ]
    for p in placed:
        lines.append(
            f";   {p['id']:24s} at X{p['x_mm']:>7.1f} Y{p['y_mm']:>7.1f}  "
            f"({p['width_mm']:.0f} × {p['height_mm']:.0f} mm)"
        )
    for p in unplaced:
        lines.append(f";   {p['id']:24s} UNPLACED — {p.get('reason')}")
    lines.append("")

    if not placed:
        lines += [
            "; (no furniture footprints to nest — emitting a no-op program)",
            "M30",
        ]
        return {
            "content_type": "text/x-gcode",
            "filename": f"{_safe_name(project_name)}-routing.gcode",
            "bytes": "\n".join(lines).encode("ascii", errors="replace"),
        }

    # Pass 1 — T1 contour.
    t1 = TOOLS[0]
    lines += _tool_change(t1, safe_z)
    lines.append(f"G0 Z{safe_z:.2f}")
    for p in placed:
        lines += _contour(
            p, tool_r=t1["diameter_mm"] / 2,
            depth_mm=contour_depth, step_mm=3.0,
            feed=t1["feed_mm_min"], plunge=t1["plunge_mm_min"],
            safe_z=safe_z,
        )

    # Pass 2 — T2 rebate.
    t2 = TOOLS[1]
    lines += _tool_change(t2, safe_z)
    for p in placed:
        lines += _rebate(
            p, depth_mm=rebate_depth,
            feed=t2["feed_mm_min"], plunge=t2["plunge_mm_min"],
            safe_z=safe_z,
        )

    # Pass 3 — T3 drilling.
    t3 = TOOLS[2]
    lines += _tool_change(t3, safe_z)
    for p in placed:
        lines += _pilot_holes(
            p, depth_mm=pilot_depth,
            feed=t3["feed_mm_min"], plunge=t3["plunge_mm_min"],
            safe_z=safe_z,
        )

    # Footer.
    lines += [
        "",
        "M5",
        f"G0 Z{safe_z * 2:.2f}",
        "G0 X0 Y0",
        "M30",
    ]

    payload = "\n".join(lines).encode("ascii", errors="replace")
    return {
        "content_type": "text/x-gcode",
        "filename": f"{_safe_name(project_name)}-routing.gcode",
        "bytes": payload,
    }
