"""G-code exporter — RS-274 contour toolpath for CNC cutout.

Per BRD Layer 5A "NC / G-Code + nesting optimization". Emits one
contour-routing pass per furniture footprint at a configurable cut depth,
suitable as a starting point for a CNC shop. Not a substitute for CAM —
users should review feeds/speeds + tool for their machine.

Conventions:
  - Units: millimetres (G21)
  - Absolute positioning (G90)
  - XY plane (G17)
  - Single flat end-mill, 6mm default
  - Z safe height = 5 mm, cut depth configurable via bundle meta
"""

from __future__ import annotations

from datetime import datetime, timezone


def _m_to_mm(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v if v > 20 else v * 1000.0


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta", {})
    project_name = meta.get("project_name") or "KATHA Project"

    # Defaults — override via meta in future.
    tool_dia_mm = 6.0
    feed_mm_min = 1200
    plunge_mm_min = 400
    rpm = 18000
    cut_depth_mm = 6.0
    pass_step_mm = 3.0
    safe_z_mm = 5.0

    lines: list[str] = []
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines += [
        f"; KATHA AI — CNC contour toolpath",
        f"; project: {project_name}",
        f"; generated: {ts}",
        f"; tool: {tool_dia_mm:.1f}mm flat end mill",
        f"; units: mm, absolute, XY plane",
        f"; feed={feed_mm_min} mm/min, plunge={plunge_mm_min} mm/min, rpm={rpm}",
        "",
        "G21",          # mm
        "G90",          # absolute
        "G17",          # XY plane
        "G54",          # work coordinate system
        f"M3 S{rpm}",   # spindle on
        f"G0 Z{safe_z_mm:.2f}",
    ]

    furniture_types = {"sofa", "chair", "dining_chair", "lounge_chair", "office_chair",
                       "dining_table", "coffee_table", "desk", "console_table", "side_table",
                       "bed", "bookshelf", "wardrobe", "cabinet", "tv_unit", "media_console"}

    routed = 0
    for obj in graph.get("objects", []):
        otype = (obj.get("type") or "").lower()
        if otype not in furniture_types:
            continue

        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        l_mm = max(_m_to_mm(d.get("length")) or 400.0, 50.0)
        w_mm = max(_m_to_mm(d.get("width")) or 400.0, 50.0)
        cx_mm = float(pos.get("x", 0)) * 1000.0
        cy_mm = float(pos.get("z", 0)) * 1000.0

        # Tool-offset corners (tool walks outside the footprint).
        r = tool_dia_mm / 2.0
        x1 = cx_mm - l_mm / 2 - r
        y1 = cy_mm - w_mm / 2 - r
        x2 = cx_mm + l_mm / 2 + r
        y2 = cy_mm + w_mm / 2 + r

        lines += [
            "",
            f"; -- {obj.get('id') or otype}  ({l_mm:.1f} x {w_mm:.1f} mm) --",
            f"G0 X{x1:.2f} Y{y1:.2f}",
            f"G0 Z{safe_z_mm:.2f}",
        ]

        # Multi-pass plunge.
        current_z = 0.0
        while current_z > -cut_depth_mm + 1e-6:
            current_z = max(current_z - pass_step_mm, -cut_depth_mm)
            lines.append(f"G1 Z{current_z:.2f} F{plunge_mm_min}")
            # Rectangular contour.
            lines += [
                f"G1 X{x2:.2f} Y{y1:.2f} F{feed_mm_min}",
                f"G1 X{x2:.2f} Y{y2:.2f}",
                f"G1 X{x1:.2f} Y{y2:.2f}",
                f"G1 X{x1:.2f} Y{y1:.2f}",
            ]
        lines.append(f"G0 Z{safe_z_mm:.2f}")
        routed += 1

    lines += [
        "",
        "M5",           # spindle off
        f"G0 Z{safe_z_mm * 2:.2f}",
        "G0 X0 Y0",
        "M30",          # program end
    ]

    if routed == 0:
        lines.insert(8, "; (no furniture footprints found to route)")

    payload = "\n".join(lines).encode("ascii", errors="replace")
    return {
        "content_type": "text/x-gcode",
        "filename": f"{_safe_name(project_name)}-contours.gcode",
        "bytes": payload,
    }


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "project"
