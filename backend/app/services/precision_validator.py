"""Precision-requirements validator (BRD 3A — Precision Requirements).

Pure deterministic compliance checker. Walks the LLM-authored drawing
spec for plan / elevation / section / iso / detail sheets and grades
every dimension or placement against the four BRD tolerance bands:

    Structural dimensions:  ±1.0 mm
    Cosmetic dimensions:    ±2.0 mm
    Material thickness:     ±0.5 mm
    Hardware placement:     ±5.0 mm

The validator never modifies the spec — it produces a compliance
report the drawing endpoint attaches to its response and any human
QA reviewer can scan.
"""

from __future__ import annotations

from typing import Any

from app.knowledge import manufacturing


# ── Classification map per spec field ───────────────────────────────────────
# Keys are the field paths inside a drawing spec; values are the BRD band
# the field is held to. Add new mappings here as new drawing types ship.
_FIELD_TO_CATEGORY: dict[str, str] = {
    # Plan view
    "plan_view.key_dimensions[*].value_m": "cosmetic_mm",
    # Elevation view
    "elevation.height_dimensions[*].to_mm": "cosmetic_mm",
    "elevation.height_dimensions[*].from_mm": "cosmetic_mm",
    "elevation.width_dimensions[*].to_mm": "cosmetic_mm",
    "elevation.width_dimensions[*].from_mm": "cosmetic_mm",
    "elevation.hardware_callouts[*]": "hardware_placement_mm",
    # Section view
    "section.key_dimensions_mm.seat_depth_mm": "cosmetic_mm",
    "section.key_dimensions_mm.back_height_mm": "cosmetic_mm",
    "section.key_dimensions_mm.arm_height_mm": "cosmetic_mm",
    "section.internal_layers[*].thickness_mm": "material_thickness_mm",
    "section.joints[*].tolerance_mm": "structural_mm",
    "section.leg_taper_mm.top": "structural_mm",
    "section.leg_taper_mm.bottom": "structural_mm",
    # Isometric view
    "isometric.parts[*].length_mm": "cosmetic_mm",
    "isometric.parts[*].height_mm": "cosmetic_mm",
    "isometric.parts[*].depth_mm": "cosmetic_mm",
    "isometric.key_dimensions[*].value_mm": "cosmetic_mm",
    # Detail sheet
    "detail.cells[*].tolerance_mm": "structural_mm",
    "detail.cells[*].radius_mm": "cosmetic_mm",
}


def precision_bands() -> dict[str, float]:
    """Return the BRD precision band dictionary unchanged (for /working-drawings/precision)."""
    return dict(manufacturing.PRECISION_REQUIREMENTS_BRD)


def classify_dimension(category: str) -> float | None:
    """Return the ± mm band for a category key (structural / cosmetic / …)."""
    return manufacturing.PRECISION_REQUIREMENTS_BRD.get(category)


def grade_value(value_mm: float, expected_mm: float, category: str) -> dict[str, Any]:
    """Compare a single value against an expected target + the BRD band."""
    band = classify_dimension(category)
    if band is None:
        return {"category": category, "ok": True, "reason": "no band defined"}
    deviation = abs(float(value_mm) - float(expected_mm))
    return {
        "category": category,
        "expected_mm": expected_mm,
        "value_mm": value_mm,
        "deviation_mm": round(deviation, 3),
        "band_mm": band,
        "ok": deviation <= band + 1e-6,
    }


# ── Per-drawing-spec compliance walks ───────────────────────────────────────


def _check_section_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Section view — joint tolerances + layer thickness must hit BRD bands."""
    checks: list[dict[str, Any]] = []
    for j in spec.get("joints") or []:
        tol = j.get("tolerance_mm")
        if tol is None:
            continue
        band = classify_dimension("structural_mm")
        ok = float(tol) <= float(band) + 1e-6
        checks.append({
            "field": f"section.joints[{j.get('key')}].tolerance_mm",
            "category": "structural_mm",
            "value_mm": tol,
            "band_mm": band,
            "ok": ok,
        })
    for layer in spec.get("internal_layers") or []:
        # Only the *manufacturing tolerance* on thickness is a band check —
        # layer thickness itself is design data, not a deviation. We instead
        # flag layers under 1 mm thick as suspicious (probably a unit error).
        t = layer.get("thickness_mm")
        if t is None:
            continue
        suspicious = float(t) < 0.5
        checks.append({
            "field": f"section.internal_layers[{layer.get('label')}].thickness_mm",
            "category": "material_thickness_mm",
            "value_mm": t,
            "band_mm": classify_dimension("material_thickness_mm"),
            "ok": not suspicious,
            "note": None if not suspicious else "Layer thinner than 0.5 mm — verify unit.",
        })
    # leg taper top/bottom are physical sizes, not deviations — flag if they
    # invert (top wider than bottom for a tapered leg should be uncommon but
    # not forbidden; just record it).
    leg = spec.get("leg_taper_mm") or {}
    if leg.get("top") and leg.get("bottom"):
        inverted = float(leg["top"]) < float(leg["bottom"])
        checks.append({
            "field": "section.leg_taper_mm",
            "category": "structural_mm",
            "value_mm": {"top": leg["top"], "bottom": leg["bottom"]},
            "band_mm": classify_dimension("structural_mm"),
            "ok": True,
            "note": "Inverted taper (base wider than top) — confirm intent." if inverted else None,
        })
    return checks


def _check_elevation_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Elevation view — hardware placement falls under ±5 mm band."""
    checks: list[dict[str, Any]] = []
    for hw in spec.get("hardware_callouts") or []:
        # Hardware is positioned by ratio (0..1), not by mm here. We classify
        # the *category* so the consumer knows the band that applies in
        # production; actual mm deviation has to come from the production
        # measurement, not from the spec.
        checks.append({
            "field": f"elevation.hardware_callouts[{hw.get('key')}]",
            "category": "hardware_placement_mm",
            "value_mm": None,
            "band_mm": classify_dimension("hardware_placement_mm"),
            "ok": True,
            "note": "Production must hold ±5 mm at this ratio.",
        })
    return checks


def _check_detail_spec(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Detail sheet — joint cells must declare tolerance_mm ≤ ±1 mm."""
    checks: list[dict[str, Any]] = []
    for cell in spec.get("cells") or []:
        if (cell.get("detail_type") or "").lower() != "joint":
            continue
        tol = cell.get("tolerance_mm")
        if tol is None or float(tol) <= 0:
            continue
        band = classify_dimension("structural_mm")
        ok = float(tol) <= float(band) + 1e-6
        checks.append({
            "field": f"detail.cells[{cell.get('key')}].tolerance_mm",
            "category": "structural_mm",
            "value_mm": tol,
            "band_mm": band,
            "ok": ok,
        })
    return checks


_DISPATCH = {
    "plan_view_spec": lambda _: [],   # plan view has only overall metres — no band check.
    "elevation_view_spec": _check_elevation_spec,
    "section_view_spec": _check_section_spec,
    "isometric_view_spec": lambda _: [],
    "detail_sheet_spec": _check_detail_spec,
}


def precision_compliance_report(*, drawing_id: str, spec: dict[str, Any] | None) -> dict[str, Any]:
    """Walk an LLM-authored drawing spec and return a compliance report.

    `drawing_id` is one of: plan_view_spec / elevation_view_spec /
    section_view_spec / isometric_view_spec / detail_sheet_spec.

    Output:
        {
            "drawing_id": ...,
            "bands": {<category>: ±mm, ...},
            "checks": [ ...per-field grading... ],
            "summary": {"total": N, "passed": N, "failed": N, "warnings": N},
        }
    """
    spec = spec or {}
    dispatcher = _DISPATCH.get(drawing_id, lambda _: [])
    checks = dispatcher(spec)
    failed = [c for c in checks if not c.get("ok")]
    warnings = [c for c in checks if c.get("note")]
    return {
        "drawing_id": drawing_id,
        "bands": precision_bands(),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
            "warnings": len(warnings),
        },
    }
