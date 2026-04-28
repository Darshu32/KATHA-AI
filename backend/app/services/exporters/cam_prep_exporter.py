"""CAM prep exporter — workshop-ready bundle (BRD Layer 5A).

Per BRD: Cutting patterns (laser, waterjet, CNC), nesting layouts
(material optimisation), quality check points marked, sequential
assembly. Emitted as a single zip the workshop manager hands to the
shop floor along with the G-code.

Bundle layout:
    cutting_patterns.svg     — 1:1 nest drawing with kerf gaps and
                               labels (ready for laser, waterjet, CNC,
                               or a print plotter)
    nesting_layout.json      — machine-readable nest (sheet, parts,
                               coordinates, sheet utilisation)
    quality_checkpoints.csv  — QA stations sequenced through the build,
                               pulled from the manufacturing spec when
                               present, fallback to BRD QA gate set
    assembly_sequence.csv    — numbered assembly steps with tools,
                               estimated minutes, and torque values for
                               critical fasteners
    tool_specifications.csv  — every tool the program calls (slot,
                               diameter, rpm, feed, plunge, use)
    README.md                — short description of every file
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from app.services.exporters.gcode_exporter import (
    SHEET_KERF_MM, SHEET_THICKNESS_MM, SHEET_W_MM, SHEET_H_MM,
    TOOLS, FURNITURE_TYPES, _nest_parts, _utilisation, _m_to_mm,
)


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "project")).strip("-") or "project"


# ── SVG nest pattern ────────────────────────────────────────────────────────


def _svg_nest(parts: list[dict], project_name: str, *, sheet_w: float = SHEET_W_MM,
              sheet_h: float = SHEET_H_MM) -> str:
    """1:1 mm SVG cutting pattern. Each part is a labelled rectangle with kerf."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts_svg: list[str] = []
    for p in parts:
        if not p.get("placed"):
            continue
        x, y, w, h = p["x_mm"], p["y_mm"], p["width_mm"], p["height_mm"]
        label = escape(f"{p['id']}  {w:.0f}×{h:.0f}")
        parts_svg.append(
            f'<g><rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'fill="#fff8ed" stroke="#3d3a36" stroke-width="0.6"/>'
            f'<text x="{x + 8:.2f}" y="{y + 24:.2f}" font-family="Arial" '
            f'font-size="14" fill="#3d3a36">{label}</text></g>'
        )

    unplaced = [p for p in parts if not p.get("placed")]
    legend_y = sheet_h + 60
    legend_lines = [
        f'<text x="0" y="{legend_y:.0f}" font-family="Arial" font-size="14" fill="#3d3a36">'
        f'KATHA AI · {escape(project_name)} · cutting pattern · {today} · '
        f'sheet {int(sheet_w)} × {int(sheet_h)} mm · '
        f'utilisation {_utilisation(parts):.1f} %</text>'
    ]
    if unplaced:
        legend_lines.append(
            f'<text x="0" y="{legend_y + 22:.0f}" font-family="Arial" font-size="12" '
            f'fill="#a85a2c">UNPLACED ({len(unplaced)}): '
            f'{escape(", ".join(p["id"] for p in unplaced))}</text>'
        )

    view_h = sheet_h + 100
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="-20 -20 {sheet_w + 40:.0f} {view_h:.0f}" '
        f'width="{sheet_w / 5:.0f}mm" height="{view_h / 5:.0f}mm">'
        f'<title>{escape(project_name)} — cutting pattern</title>'
        f'<rect x="0" y="0" width="{sheet_w:.0f}" height="{sheet_h:.0f}" '
        f'fill="#efe9df" stroke="#3d3a36" stroke-width="2"/>'
        + "".join(parts_svg) + "".join(legend_lines)
        + '</svg>'
    )


# ── Quality check points ────────────────────────────────────────────────────


_DEFAULT_QA_GATES = [
    {"stage": "material_inspection", "check_point": "Confirm panels match grade and moisture content < 12 %.", "tool": "moisture meter"},
    {"stage": "dimension_verification", "check_point": "Verify cut parts within ±2 mm; diagonals equal.", "tool": "tape + square"},
    {"stage": "rebate_check", "check_point": "Rebate depth uniform; no spelching on entry/exit.", "tool": "depth gauge"},
    {"stage": "finish_inspection", "check_point": "Surface sanded to grit 220, no cross-grain scratches.", "tool": "raking light"},
    {"stage": "assembly_check", "check_point": "Frame square ±2 mm; no rocking; gaps < 1 mm at joints.", "tool": "square + feeler gauge"},
    {"stage": "safety_testing", "check_point": "Tip test 10° off-axis with rated load; static load × hold.", "tool": "calibrated weights"},
]


def _qa_checkpoints(spec: dict) -> list[dict]:
    manufacturing = spec.get("manufacturing") or {}
    qa_block = manufacturing.get("quality_assurance") or {}
    rows: list[dict] = []
    for i, qc in enumerate(qa_block.get("quality_checkpoints") or [], start=1):
        rows.append({
            "step": i,
            "stage": qc.get("test_type", "—"),
            "method": qc.get("method", "—"),
            "acceptance_criterion": qc.get("acceptance_criterion", "—"),
            "tool": qc.get("tool") or "—",
        })
    if rows:
        return rows
    # Fallback to BRD default gates.
    return [{"step": i + 1, "stage": g["stage"], "method": g["check_point"],
             "acceptance_criterion": "BRD default tolerance", "tool": g["tool"]}
            for i, g in enumerate(_DEFAULT_QA_GATES)]


# ── Assembly sequence ───────────────────────────────────────────────────────


_DEFAULT_ASSEMBLY = [
    {"step": 1, "title": "Pre-fit dry assembly",  "detail": "Lay out cut parts, dry-fit M&T joinery; verify shoulder gaps.",  "tools_required": "rubber mallet; square", "estimated_minutes": 30, "critical_fastener": "", "torque_nm": 0},
    {"step": 2, "title": "Glue + clamp frame",    "detail": "Apply PVA D3 to all faying surfaces; clamp diagonals.",          "tools_required": "PVA D3; bar clamps; square", "estimated_minutes": 45, "critical_fastener": "", "torque_nm": 0},
    {"step": 3, "title": "Drop in panels",        "detail": "Insert back panel into rebate; secure with brad nails.",          "tools_required": "brad nailer", "estimated_minutes": 25, "critical_fastener": "", "torque_nm": 0},
    {"step": 4, "title": "Mount hardware",        "detail": "Fit corner brackets and feet at pilot locations.",                "tools_required": "torque wrench; M5 hex driver", "estimated_minutes": 20, "critical_fastener": "M5 × 30 bolt", "torque_nm": 6},
    {"step": 5, "title": "Final inspection",      "detail": "Square check ±2 mm; rocking test; finish wipe-down.",            "tools_required": "tape; square; clean rag", "estimated_minutes": 15, "critical_fastener": "", "torque_nm": 0},
]


def _assembly_sequence(spec: dict) -> list[dict]:
    manufacturing = spec.get("manufacturing") or {}
    qa_block = manufacturing.get("quality_assurance") or {}
    seq = qa_block.get("assembly_sequence") or []
    rows: list[dict] = []
    for s in seq:
        tools = s.get("tools_required") or []
        rows.append({
            "step": s.get("step"),
            "title": s.get("title", "—"),
            "detail": s.get("detail", "—"),
            "tools_required": ", ".join(tools) if isinstance(tools, list) else str(tools),
            "estimated_minutes": s.get("estimated_minutes", 0),
            "critical_fastener": "",
            "torque_nm": 0,
        })
    # Layer hardware rows in if present.
    for hw in qa_block.get("hardware_installation") or []:
        if (hw.get("critical") or "").lower() == "yes":
            rows.append({
                "step": (rows[-1]["step"] if rows else 0) + 1,
                "title": f"Install {hw.get('fastener', 'fastener')}",
                "detail": hw.get("notes") or "—",
                "tools_required": "torque wrench",
                "estimated_minutes": 10,
                "critical_fastener": hw.get("fastener", "—"),
                "torque_nm": hw.get("torque_nm", 0),
            })
    return rows or _DEFAULT_ASSEMBLY


# ── Tool specifications CSV ─────────────────────────────────────────────────


def _tool_spec_rows() -> list[dict]:
    return [{
        "slot": t["slot"],
        "name": t["name"],
        "diameter_mm": t["diameter_mm"],
        "flutes": t["flutes"],
        "rpm": t["rpm"],
        "feed_mm_min": t["feed_mm_min"],
        "plunge_mm_min": t["plunge_mm_min"],
        "use": t["use"],
    } for t in TOOLS]


# ── CSV helper ──────────────────────────────────────────────────────────────


def _to_csv(rows: list[dict]) -> bytes:
    if not rows:
        return b""
    bio = io.StringIO()
    writer = csv.DictWriter(bio, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return bio.getvalue().encode("utf-8")


# ── Public ──────────────────────────────────────────────────────────────────


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta") or {}
    project_name = meta.get("project_name") or "KATHA Project"
    project = _safe_name(project_name)
    today = datetime.now(timezone.utc).date().isoformat()
    sheet_thickness = float(meta.get("sheet_thickness_mm", SHEET_THICKNESS_MM))

    # ── Build the same nest the G-code uses ────────────────────────────────
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

    nesting_json = {
        "project": project_name,
        "generated_at": today,
        "sheet": {
            "width_mm": SHEET_W_MM, "height_mm": SHEET_H_MM,
            "kerf_mm": SHEET_KERF_MM, "thickness_mm": sheet_thickness,
            "stock": "hardwood ply",
        },
        "utilisation_pct": util,
        "placed": [
            {k: p[k] for k in ("id", "type", "width_mm", "height_mm",
                               "x_mm", "y_mm", "x2_mm", "y2_mm")}
            for p in placed
        ],
        "unplaced": [
            {"id": p["id"], "type": p["type"], "reason": p.get("reason")}
            for p in unplaced
        ],
    }

    qa_rows = _qa_checkpoints(spec)
    asm_rows = _assembly_sequence(spec)
    tool_rows = _tool_spec_rows()

    # ── README ─────────────────────────────────────────────────────────────
    readme = (
        f"# {project_name} — CAM prep bundle\n\n"
        f"Generated {today} by KATHA AI (BRD Layer 5A — Manufacturing).\n\n"
        "Contents:\n\n"
        "| File | Purpose |\n"
        "|---|---|\n"
        "| cutting_patterns.svg | 1:1 mm cutting pattern; ready for laser / waterjet / CNC / plotter print |\n"
        "| nesting_layout.json | Machine-readable nest — sheet, kerf, placed parts with x/y, sheet utilisation |\n"
        "| quality_checkpoints.csv | Quality stations sequenced through the build (from the manufacturing spec) |\n"
        "| assembly_sequence.csv | Numbered assembly steps with tools, estimated minutes, critical fastener torques |\n"
        "| tool_specifications.csv | Tool slots, diameters, rpm, feed, plunge — matches the routing G-code header |\n"
        f"\nSheet: {int(SHEET_W_MM)} × {int(SHEET_H_MM)} × {int(sheet_thickness)} mm "
        f"hardwood ply · kerf {int(SHEET_KERF_MM)} mm · utilisation {util:.1f} %.\n"
    )

    bio = io.BytesIO()
    with zipfile.ZipFile(bio, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", readme)
        zf.writestr("cutting_patterns.svg", _svg_nest(nested, project_name))
        zf.writestr("nesting_layout.json", json.dumps(nesting_json, indent=2))
        zf.writestr("quality_checkpoints.csv", _to_csv(qa_rows))
        zf.writestr("assembly_sequence.csv", _to_csv(asm_rows))
        zf.writestr("tool_specifications.csv", _to_csv(tool_rows))

    return {
        "content_type": "application/zip",
        "filename": f"{project}-cam-prep.zip",
        "bytes": bio.getvalue(),
    }
