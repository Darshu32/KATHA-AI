"""Post-generation validator for design graphs.

Checks an LLM-generated (or user-edited) design graph against the
Layer 1 knowledge base and returns a structured list of warnings +
recommendations. Non-blocking: it never raises; it annotates.

Usage (from ai_orchestrator or a pipeline stage):

    from app.services.knowledge_validator import validate_design_graph
    report = validate_design_graph(data, segment="residential")

`report` shape:
    {
        "ok": bool,                      # True if no errors (warnings allowed)
        "errors":      [ { code, path, message } ],  # hard violations
        "warnings":    [ { code, path, message } ],  # soft flags
        "suggestions": [ { code, path, message } ],  # recommendation engine
        "summary": str,
    }
"""

from __future__ import annotations

import logging
from typing import Any

from app.knowledge import (
    clearances,
    codes,
    ergonomics,
    manufacturing,
    materials as materials_kb,
    mep,
    space_standards,
    structural,
    themes,
)

logger = logging.getLogger(__name__)

# Room type → ergonomic item bucket we check.
ROOM_TYPICAL_OBJECTS: dict[str, list[tuple[str, str]]] = {
    "bedroom": [("bed", "double"), ("wardrobe", "wardrobe")],
    "living_room": [("sofa", "lounge_chair"), ("coffee_table", "coffee_table"), ("chair", "lounge_chair")],
    "dining_room": [("dining_table", "dining_table"), ("chair", "dining_chair")],
    "kitchen": [("counter", "counter")],
    "study": [("desk", "desk"), ("chair", "office_chair")],
    "office": [("desk", "desk"), ("chair", "office_chair")],
}

# Object-type -> ergonomics category
TYPE_TO_CATEGORY: dict[str, tuple[str, str]] = {
    "chair": ("chair", "dining_chair"),
    "dining_chair": ("chair", "dining_chair"),
    "lounge_chair": ("chair", "lounge_chair"),
    "office_chair": ("chair", "office_chair"),
    "sofa": ("chair", "lounge_chair"),
    "dining_table": ("table", "dining_table"),
    "coffee_table": ("table", "coffee_table"),
    "desk": ("table", "desk"),
    "console_table": ("table", "console_table"),
    "side_table": ("table", "side_table"),
    "bed": ("bed", "double"),
    "single_bed": ("bed", "single"),
    "queen_bed": ("bed", "queen"),
    "king_bed": ("bed", "king"),
    "bookshelf": ("storage", "bookshelf"),
    "wardrobe": ("storage", "wardrobe"),
    "counter": ("storage", "counter"),
    "tv_unit": ("storage", "tv_unit"),
}


def _to_mm(value: Any) -> float | None:
    """Dimensions in the graph are in metres; convert to mm for checks."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    # Heuristic: existing graphs use metres (e.g. seat height 0.42),
    # but some ad-hoc graphs use mm (420). Treat > 20 as already mm.
    return v * 1000.0 if v < 20 else v


def _issue(code: str, path: str, message: str) -> dict:
    return {"code": code, "path": path, "message": message}


def validate_design_graph(
    data: dict,
    *,
    segment: str = "residential",
) -> dict:
    errors: list[dict] = []
    warnings: list[dict] = []
    suggestions: list[dict] = []

    room = data.get("room") or {}
    room_type = room.get("type") or data.get("room_type") or "living_room"
    dims = room.get("dimensions") or {}
    length = dims.get("length")
    width = dims.get("width")
    height = dims.get("height")

    # ── Room-level checks ────────────────────────────────────────────────────
    if length and width:
        area = float(length) * float(width)
        short_side = min(float(length), float(width))

        res = space_standards.area_check(room_type, area, segment=segment)
        if res["status"] == "warn_low":
            warnings.append(_issue("ROOM_AREA_BELOW_STANDARD", "room.dimensions", res["message"]))
        elif res["status"] == "warn_high":
            suggestions.append(_issue("ROOM_AREA_ABOVE_TYPICAL", "room.dimensions", res["message"]))

        if height:
            nbc_issues = codes.check_room_against_nbc(room_type, area, short_side, float(height))
            for iss in nbc_issues:
                errors.append(_issue("NBC_VIOLATION", "room.dimensions", f"{iss['code']}: {iss['issue']}"))

    # ── Object ergonomic checks ──────────────────────────────────────────────
    for obj in data.get("objects", []):
        otype = (obj.get("type") or "").lower()
        mapped = TYPE_TO_CATEGORY.get(otype)
        if not mapped:
            continue
        category, item = mapped
        obj_dims = obj.get("dimensions") or {}
        dim_map = {
            "chair": {"height": "seat_height_mm", "width": "overall_width_mm", "length": "overall_depth_mm"},
            "table": {"height": "height_mm", "width": "width_mm", "length": "length_mm"},
            "bed": {"height": "platform_height_mm", "width": "mattress_mm", "length": "mattress_mm"},
            "storage": {"height": "height_mm", "depth": "depth_mm"},
        }.get(category, {})
        for graph_key, range_key in dim_map.items():
            raw = obj_dims.get(graph_key)
            if raw is None:
                continue
            value_mm = _to_mm(raw)
            if value_mm is None:
                continue
            res = ergonomics.check_range(category, item, range_key, value_mm)
            if res["status"] in {"warn_low", "warn_high"}:
                warnings.append(_issue(
                    "ERGONOMIC_OUT_OF_RANGE",
                    f"objects[{obj.get('id','?')}].{graph_key}",
                    f"{otype}: {res['message']}",
                ))

    # ── Theme alignment checks ───────────────────────────────────────────────
    style = (data.get("style") or {}).get("primary") or data.get("style_primary") or ""
    pack = themes.get(style) if style else None
    if pack:
        primaries = [m.lower() for m in pack["material_palette"].get("primary", [])]
        secondary = [m.lower() for m in pack["material_palette"].get("secondary", [])]
        allowed = set(primaries) | set(secondary)
        seen_materials = [(m.get("name") or "").lower() for m in data.get("materials", [])]
        mismatched = [name for name in seen_materials if name and not any(kw in name for kw in allowed)]
        if allowed and len(mismatched) > len(seen_materials) / 2:
            suggestions.append(_issue(
                "THEME_PALETTE_DRIFT",
                "materials",
                f"Theme '{pack['display_name']}' favours {', '.join(primaries) or '—'}; "
                f"current palette leans elsewhere ({', '.join(mismatched[:3])}).",
            ))

    # ── Door clearance recommendation ────────────────────────────────────────
    for obj in data.get("objects", []):
        if (obj.get("type") or "").lower() == "door":
            w = _to_mm((obj.get("dimensions") or {}).get("width"))
            if w:
                res = clearances.check_door("interior", w)
                if res["status"] == "warn_low":
                    warnings.append(_issue("DOOR_TOO_NARROW", f"objects[{obj.get('id','?')}].width", res["message"]))

    # ── Structural span checks ───────────────────────────────────────────────
    _check_structural(data, warnings, suggestions)

    # ── MEP sanity checks ────────────────────────────────────────────────────
    _check_mep(data, room_type, warnings, suggestions)

    # ── Manufacturing feasibility checks ─────────────────────────────────────
    _check_manufacturing(data, warnings, suggestions)

    ok = len(errors) == 0
    summary = f"{len(errors)} error(s), {len(warnings)} warning(s), {len(suggestions)} suggestion(s)."
    logger.info("knowledge_validator_report", extra={"summary": summary, "segment": segment, "room_type": room_type})
    return {"ok": ok, "errors": errors, "warnings": warnings, "suggestions": suggestions, "summary": summary}


# ── Structural checks ───────────────────────────────────────────────────────

_SPAN_MATERIAL_HINTS = {
    "wood": "timber_beam", "timber": "timber_beam", "walnut": "timber_beam",
    "oak": "timber_beam", "teak": "timber_beam", "glulam": "engineered_wood_glulam",
    "steel": "steel_i_beam", "iron": "steel_i_beam",
    "concrete": "rcc_beam", "rcc": "rcc_beam",
}


def _check_structural(data: dict, warnings: list[dict], suggestions: list[dict]) -> None:
    """Flag objects whose primary horizontal span exceeds material limits."""
    for obj in data.get("objects", []):
        otype = (obj.get("type") or "").lower()
        if otype not in {"beam", "shelf", "bookshelf", "dining_table", "desk", "console_table"}:
            continue
        dims = obj.get("dimensions") or {}
        longest_m = max(
            _to_m(dims.get("length")) or 0.0,
            _to_m(dims.get("width")) or 0.0,
        )
        if longest_m <= 0:
            continue
        mat_name = (obj.get("material") or "").lower()
        span_cat = next((v for k, v in _SPAN_MATERIAL_HINTS.items() if k in mat_name), None)
        if not span_cat:
            continue
        res = structural.check_span(span_cat, longest_m)
        if res["status"] == "warn_high":
            warnings.append(_issue(
                "STRUCTURAL_SPAN_EXCEEDED",
                f"objects[{obj.get('id','?')}].span",
                res["message"],
            ))


# ── MEP checks ──────────────────────────────────────────────────────────────

def _check_mep(data: dict, room_type: str, warnings: list[dict], suggestions: list[dict]) -> None:
    room = data.get("room") or {}
    dims = room.get("dimensions") or {}
    length = _to_m(dims.get("length"))
    width = _to_m(dims.get("width"))
    height = _to_m(dims.get("height"))
    if not (length and width and height):
        return
    area = length * width
    volume = area * height

    # Ventilation / fresh-air target.
    cfm_calc = mep.hvac_cfm(volume, room_type)
    if "error" not in cfm_calc:
        suggestions.append(_issue(
            "HVAC_FRESH_AIR_TARGET",
            "room.dimensions",
            f"Plan fresh-air supply around {cfm_calc['cfm_total']} CFM "
            f"({cfm_calc['ach']} ACH x {volume:.1f} m^3).",
        ))

    # Lighting circuits needed (residential default).
    use_profile = {
        "office": "office_general",
        "study": "residential",
        "living_room": "residential",
        "bedroom": "residential",
        "kitchen": "residential",
        "dining_room": "residential",
        "restaurant": "restaurant",
        "retail": "retail",
    }.get(room_type, "residential")
    lp = mep.lighting_circuits(area, use_profile)
    suggestions.append(_issue(
        "LIGHTING_POWER_TARGET",
        "room.dimensions",
        f"Lighting load ~{lp['total_load_w']}W (density {lp['density_w_m2']} W/m^2) "
        f"— plan {lp['lighting_circuits']} dedicated lighting circuit(s).",
    ))


# ── Manufacturing feasibility checks ────────────────────────────────────────

def _check_manufacturing(data: dict, warnings: list[dict], suggestions: list[dict]) -> None:
    """Surface lead-time + tolerance advisories for wood / metal furniture."""
    for obj in data.get("objects", []):
        mat_name = (obj.get("material") or "").lower()
        otype = (obj.get("type") or "").lower()

        # Wood lead-time suggestion for solid-wood furniture.
        if any(species in mat_name for species in ("walnut", "oak", "teak", "rosewood")):
            lt = manufacturing.lead_time_for("woodworking_furniture")
            if lt:
                suggestions.append(_issue(
                    "MFG_LEAD_TIME_WOOD",
                    f"objects[{obj.get('id','?')}].material",
                    f"Solid-wood '{otype}' typically runs {lt[0]}-{lt[1]} weeks end-to-end.",
                ))
        elif any(metal in mat_name for metal in ("steel", "iron", "brass", "aluminium", "aluminum")):
            lt = manufacturing.lead_time_for("metal_fabrication")
            if lt:
                suggestions.append(_issue(
                    "MFG_LEAD_TIME_METAL",
                    f"objects[{obj.get('id','?')}].material",
                    f"Metal fabrication for '{otype}' typically runs {lt[0]}-{lt[1]} weeks.",
                ))

    # Tolerance awareness: if the graph hints at precision work, remind of ±0.5mm limit.
    for obj in data.get("objects", []):
        meta = obj.get("metadata") or {}
        if meta.get("precision") == "high":
            tol = manufacturing.tolerance_for("woodworking_precision")
            if tol:
                suggestions.append(_issue(
                    "MFG_TOLERANCE_PRECISION",
                    f"objects[{obj.get('id','?')}].metadata.precision",
                    f"Precision marked high — holds +/-{tol}mm; confirm CNC capability.",
                ))


def _to_m(value) -> float | None:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    # Heuristic: values > 20 are almost certainly mm; convert.
    return v / 1000.0 if v > 20 else v
