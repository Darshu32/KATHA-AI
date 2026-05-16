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

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.standards.codes_lookup import (
    check_room_against_nbc as _check_room_against_nbc_db,
)
from app.services.standards.ergonomics_lookup import (
    check_range as _check_ergo_range_db,
)
from app.services.standards.manufacturing_lookup import (
    lead_time_for as _mfg_lead_time_for_db,
    list_qa_gates as _mfg_list_qa_gates_db,
    moq_for as _mfg_moq_for_db,
    tolerance_for as _mfg_tolerance_for_db,
)
from app.services.standards.materials_lookup import (
    KNOWN_FINISHES as _KNOWN_FINISHES,
    check_metal_property as _check_metal_property_db,
    check_upholstery_durability as _check_upholstery_durability_db,
    check_upholstery_property as _check_upholstery_property_db,
    check_wood_property as _check_wood_property_db,
    get_metal as _get_metal_db,
    get_upholstery_brd_band as _get_upholstery_brd_band_db,
    get_wood as _get_wood_db,
    resolve_finish_row as _resolve_finish_row_db,
)
from app.services.standards.knowledge_service import (
    check_corridor_width as _check_corridor_width_db,
    check_door_width as _check_door_width_db,
    check_room_area as _check_room_area_db,
    check_stair_dimensions as _check_stair_dimensions_db,
    resolve_standard as _resolve_standard_db,
)
from app.services.standards.mep_sizing import (
    hvac_cfm as _hvac_cfm_db,
    lighting_circuits as _lighting_circuits_db,
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


# ── BRD §1B / §4.2 — DB-backed validator (use this when a session is available)


async def validate_design_graph_async(
    data: dict,
    *,
    segment: str = "residential",
    session: AsyncSession,
    jurisdiction: str = "india_nbc",
) -> dict:
    """Same shape as :func:`validate_design_graph`, but the room-area
    check sources from the ``building_standards`` DB table instead of
    the deprecated Python-literal module.

    Everything else (ergonomics, structural, MEP, manufacturing,
    theme, NBC code clauses) delegates to the existing sync function;
    we re-call it under the hood and replace its room-area warning
    with the DB-cited equivalent so the report carries the canonical
    NBC clause + jurisdiction.

    Use this from any path that has an :class:`AsyncSession` (generation
    pipeline, the ``/validate`` HTTP route). Read-only.
    """
    report = validate_design_graph(data, segment=segment)

    room = data.get("room") or {}
    room_type = room.get("type") or data.get("room_type") or "living_room"
    dims = room.get("dimensions") or {}
    length = dims.get("length")
    width = dims.get("width")

    # ── Room area (BRD §1B / §4.2 space planning) ─────────────────
    if length and width:
        def _is_area_issue(item: dict) -> bool:
            return item.get("code") in {
                "ROOM_AREA_BELOW_STANDARD",
                "ROOM_AREA_ABOVE_TYPICAL",
            }

        report["warnings"] = [
            w for w in report.get("warnings", []) if not _is_area_issue(w)
        ]
        report["suggestions"] = [
            s for s in report.get("suggestions", []) if not _is_area_issue(s)
        ]

        area = float(length) * float(width)
        db_res = await _check_room_area_db(
            session,
            room_type=room_type,
            area_m2=area,
            segment=segment,
            jurisdiction=jurisdiction,
        )
        if db_res.get("status") == "warn_low":
            report["warnings"].append(
                {
                    "code": "ROOM_AREA_BELOW_STANDARD",
                    "path": "room.dimensions",
                    "message": db_res["message"],
                    "reference": db_res.get("reference"),
                    "source_section": db_res.get("source_section"),
                    "jurisdiction": db_res.get("jurisdiction_used") or jurisdiction,
                }
            )
        elif db_res.get("status") == "warn_high":
            report["suggestions"].append(
                {
                    "code": "ROOM_AREA_ABOVE_TYPICAL",
                    "path": "room.dimensions",
                    "message": db_res["message"],
                    "reference": db_res.get("reference"),
                    "source_section": db_res.get("source_section"),
                    "jurisdiction": db_res.get("jurisdiction_used") or jurisdiction,
                }
            )

    # ── NBC habitable / kitchen / bathroom code check (BRD §1B) ──
    # The sync validator (above) already emitted NBC_VIOLATION errors
    # using the deprecated Python literal. Replace them with cited
    # DB-backed equivalents so each error carries source_section.
    if length and width:
        room_height = dims.get("height")
        room_short_side = min(float(length), float(width))
        room_area = float(length) * float(width)

        report["errors"] = [
            e for e in report.get("errors", []) if e.get("code") != "NBC_VIOLATION"
        ]

        if room_height:
            try:
                height_m = float(room_height)
            except (TypeError, ValueError):
                height_m = 0.0
            if height_m > 0:
                nbc_issues = await _check_room_against_nbc_db(
                    session,
                    room_type=room_type,
                    area_m2=room_area,
                    short_side_m=room_short_side,
                    height_m=height_m,
                    jurisdiction=jurisdiction,
                )
                nbc_row = await _resolve_standard_db(
                    session,
                    slug="code_nbc_minimum_room_dimensions",
                    category="code",
                    jurisdiction=jurisdiction,
                )
                for issue in nbc_issues:
                    # The accessor returns ``{code, issue}`` shaped
                    # entries — promote to the validator's error format.
                    report["errors"].append(
                        {
                            "code": "NBC_VIOLATION",
                            "path": "room.dimensions",
                            "message": f"{issue.get('code', 'NBC')}: {issue.get('issue', '')}",
                            "reference": (nbc_row or {}).get("notes")
                            or (nbc_row or {}).get("display_name"),
                            "source_section": (nbc_row or {}).get("source_section"),
                            "jurisdiction": (nbc_row or {}).get("jurisdiction")
                            or jurisdiction,
                        }
                    )

    # ── Clearance & egress (BRD §1B) — DB-backed, citation-carrying.
    # Drop sync clearance entries first so we don't double-warn.
    _CLEARANCE_CODES = {
        "DOOR_TOO_NARROW",
        "DOOR_WIDTH_OUT_OF_BAND",
        "CORRIDOR_TOO_NARROW",
        "STAIR_GEOMETRY_OUT_OF_BAND",
    }
    report["warnings"] = [
        w for w in report.get("warnings", []) if w.get("code") not in _CLEARANCE_CODES
    ]

    # Default corridor segment for residential / commercial / hospital.
    # Hospital is its own row in the DB; everything else maps cleanly.
    corridor_segment_default = (
        "hospital"
        if room_type in {"ward", "hospital_room"}
        else ("commercial" if segment == "commercial" else "residential")
    )

    for obj in data.get("objects", []) or []:
        otype = (obj.get("type") or "").lower()
        obj_id = obj.get("id", "?")

        if otype == "door":
            w_mm = _to_mm((obj.get("dimensions") or {}).get("width"))
            if w_mm is None:
                continue
            # Architects may tag the door's purpose (entry / interior /
            # bathroom / sliding / emergency_egress). Default to
            # ``interior`` so a graph that just says "door" still gets
            # the most relevant standard.
            meta = obj.get("metadata") or {}
            door_type = (
                meta.get("door_type")
                or obj.get("door_type")
                or obj.get("subtype")
                or "interior"
            )
            res = await _check_door_width_db(
                session, door_type=door_type, width_mm=w_mm, jurisdiction=jurisdiction
            )
            if res.get("status") == "warn_low":
                report["warnings"].append(
                    {
                        "code": "DOOR_TOO_NARROW",
                        "path": f"objects[{obj_id}].width",
                        "message": res["message"],
                        "reference": res.get("reference"),
                        "source_section": res.get("source_section"),
                        "jurisdiction": res.get("jurisdiction_used") or jurisdiction,
                    }
                )
            elif res.get("status") == "warn_high":
                report["suggestions"].append(
                    {
                        "code": "DOOR_WIDTH_OUT_OF_BAND",
                        "path": f"objects[{obj_id}].width",
                        "message": res["message"],
                        "reference": res.get("reference"),
                        "source_section": res.get("source_section"),
                        "jurisdiction": res.get("jurisdiction_used") or jurisdiction,
                    }
                )

        elif otype in {"corridor", "hallway", "passage"}:
            w_mm = _to_mm((obj.get("dimensions") or {}).get("width"))
            if w_mm is None:
                continue
            meta = obj.get("metadata") or {}
            corridor_segment = (
                meta.get("corridor_segment")
                or obj.get("corridor_segment")
                or corridor_segment_default
            )
            res = await _check_corridor_width_db(
                session,
                segment=corridor_segment,
                width_mm=w_mm,
                jurisdiction=jurisdiction,
            )
            if res.get("status") == "warn_low":
                report["warnings"].append(
                    {
                        "code": "CORRIDOR_TOO_NARROW",
                        "path": f"objects[{obj_id}].width",
                        "message": res["message"],
                        "reference": res.get("reference"),
                        "source_section": res.get("source_section"),
                        "jurisdiction": res.get("jurisdiction_used") or jurisdiction,
                    }
                )

        elif otype in {"stair", "stairs", "staircase"}:
            d = obj.get("dimensions") or {}
            meta = obj.get("metadata") or {}
            stair_type = (
                meta.get("stair_type")
                or obj.get("stair_type")
                or ("commercial" if segment == "commercial" else "residential")
            )
            # Stair geometry is usually given in mm — graphs that
            # store metres get up-converted by _to_mm's heuristic.
            rise = _to_mm(d.get("rise") or d.get("riser") or meta.get("rise_mm"))
            tread = _to_mm(d.get("tread") or meta.get("tread_mm"))
            stair_w = _to_mm(d.get("width") or meta.get("width_mm"))
            res = await _check_stair_dimensions_db(
                session,
                stair_type=stair_type,
                rise_mm=rise,
                tread_mm=tread,
                width_mm=stair_w,
                jurisdiction=jurisdiction,
            )
            if res.get("status") == "warn_low":
                report["warnings"].append(
                    {
                        "code": "STAIR_GEOMETRY_OUT_OF_BAND",
                        "path": f"objects[{obj_id}]",
                        "message": res["message"],
                        "reference": res.get("reference"),
                        "source_section": res.get("source_section"),
                        "jurisdiction": res.get("jurisdiction_used") or jurisdiction,
                    }
                )

    # ── Furniture ergonomics (BRD §1C) — DB-backed.
    # The sync validator above emitted ERGONOMIC_OUT_OF_RANGE warnings
    # using the deprecated Python literal. Strip them and re-emit from
    # the DB rows so each warning carries source_section + jurisdiction.
    report["warnings"] = [
        w for w in report.get("warnings", []) if w.get("code") != "ERGONOMIC_OUT_OF_RANGE"
    ]

    # Same dim-map the sync validator uses — graph_key → range_key. We
    # mirror it here rather than import so the async path is self-
    # contained and easy to extend per BRD §1C chair / table / bed /
    # storage groups.
    _DIM_MAP_BY_CATEGORY = {
        "chair": {
            "height": "seat_height_mm",
            "width": "overall_width_mm",
            "length": "overall_depth_mm",
        },
        "table": {
            "height": "height_mm",
            "width": "width_mm",
            "length": "length_mm",
            # BRD §1C tables specify a 60 cm depth minimum (dining,
            # workspace). The DB row carries ``depth_mm`` separately
            # from ``width_mm`` / ``length_mm``; add it here so a graph
            # that records ``dimensions.depth`` (perpendicular to the
            # long side) is actually checked.
            "depth": "depth_mm",
        },
        "bed": {
            # BRD §1C beds: validator checks platform height and uses
            # the single ``mattress_mm`` band (e.g. single=[900, 2000])
            # for both width and length — this is intentionally loose,
            # so a 900-wide / 2000-long single both pass. Raised-bed
            # height (BRD 55–60 cm) and under-bed storage clearance
            # (BRD 30–40 cm) are seeded as ``raised_height_mm`` +
            # ``ergonomics_bed_under_storage`` but stay dormant until
            # the design graph encodes "raised vs platform" and
            # "has under-bed storage". Tracked with the broader graph-
            # schema gaps (loads / foundations / egress paths).
            "height": "platform_height_mm",
            "width": "mattress_mm",
            "length": "mattress_mm",
        },
        "storage": {
            # BRD §1C storage — different row types carry different keys.
            # Counters / TV units / base cabinets use ``height_mm`` and
            # ``depth_mm``; tall pieces (bookshelf, wardrobe, cabinet,
            # object_shelf) use ``overall_height_mm``; shelving uses
            # ``shelf_depth_mm`` (BRD 30 cm books / 45 cm objects);
            # kitchen base cabinets and counters carry a toe-kick band
            # (BRD ≥ 10 cm minimum). Each graph dimension is checked
            # against its matching DB key — accessor returns ``unknown``
            # when the row doesn't carry that key, and we silently drop
            # ``unknown`` results so unmapped checks don't pollute the
            # report.
            "height": "height_mm",
            "depth": "depth_mm",
            "overall_height": "overall_height_mm",
            "shelf_depth": "shelf_depth_mm",
            "toe_kick_height": "toe_kick_height_mm",
        },
    }

    for obj in data.get("objects", []) or []:
        otype = (obj.get("type") or "").lower()
        mapped = TYPE_TO_CATEGORY.get(otype)
        if not mapped:
            continue
        category, item = mapped
        dim_map = _DIM_MAP_BY_CATEGORY.get(category, {})
        if not dim_map:
            continue
        obj_dims = obj.get("dimensions") or {}
        obj_id = obj.get("id", "?")
        # Fetch the row once for citation enrichment.
        ergo_row = await _resolve_standard_db(
            session,
            slug=f"ergonomics_{category}_{item}",
            category="space",
            jurisdiction=jurisdiction,
        )
        cite = (ergo_row or {}).get("source_section")
        jur = (ergo_row or {}).get("jurisdiction") or jurisdiction
        for graph_key, range_key in dim_map.items():
            raw = obj_dims.get(graph_key)
            if raw is None:
                continue
            value_mm = _to_mm(raw)
            if value_mm is None:
                continue
            res = await _check_ergo_range_db(
                session,
                category=category,
                item=item,
                dim=range_key,
                value_mm=value_mm,
                jurisdiction=jurisdiction,
            )
            if res.get("status") in {"warn_low", "warn_high"}:
                report["warnings"].append(
                    {
                        "code": "ERGONOMIC_OUT_OF_RANGE",
                        "path": f"objects[{obj_id}].{graph_key}",
                        "message": f"{otype}: {res.get('message','')}",
                        "reference": cite,
                        "source_section": cite,
                        "jurisdiction": jur,
                    }
                )

    # ── Material physical properties (BRD §1C wood) — DB-backed.
    # When a graph object carries ``material`` matching a seeded wood
    # species, check its density / MOR / MOE against the BRD §1C
    # wide envelope. Each property is checked independently — engineered
    # materials (plywood, MDF) often sit below the solid-wood floor on
    # strength, and the user should see that flagged.
    #
    # We track which (species, property) pairs we've already warned about
    # this generation so a graph with 10 plywood objects doesn't emit
    # 30 identical warnings — one per (species, property) is enough.
    _WOOD_PROPERTIES = ("density_kg_m3", "mor_mpa", "moe_mpa")
    _wood_already_warned: set[tuple[str, str]] = set()

    for obj in data.get("objects", []) or []:
        material_name = (obj.get("material") or "").strip().lower()
        if not material_name:
            continue
        # Accept common aliases for the seed species — "walnut wood" /
        # "oak veneer" / "teak top" all map to the underlying species.
        species: str | None = None
        for seeded in ("walnut", "oak", "teak", "plywood_marine", "mdf", "rubberwood"):
            if seeded in material_name or seeded.replace("_", " ") in material_name:
                species = seeded
                break
        if species is None and "plywood" in material_name:
            species = "plywood_marine"
        if species is None:
            continue

        spec = await _get_wood_db(session, species=species)
        if not spec:
            continue
        obj_id = obj.get("id", "?")
        for prop in _WOOD_PROPERTIES:
            value = spec.get(prop)
            if value is None:
                continue
            if (species, prop) in _wood_already_warned:
                continue
            res = await _check_wood_property_db(
                session,
                species=species,
                property_key=prop,
                value=float(value),
                jurisdiction=jurisdiction,
            )
            status = res.get("status")
            if status in {"warn_low", "warn_high"}:
                _wood_already_warned.add((species, prop))
                report["warnings"].append(
                    {
                        "code": "MATERIAL_OUT_OF_BRD_BAND",
                        "path": f"objects[{obj_id}].material",
                        "message": res["message"],
                        "reference": res.get("reference"),
                        "source_section": res.get("source_section"),
                        "jurisdiction": res.get("jurisdiction_used") or jurisdiction,
                    }
                )

    # ── Metal material physical properties (BRD §1C — Steel / Aluminum
    # / Brass). Same dedup pattern as wood: when a graph object's
    # ``material`` matches a seeded alloy, validate density + yield
    # against the BRD per-family expectation.
    _METAL_PROPERTIES = ("density_kg_m3", "yield_mpa")
    _metal_already_warned: set[tuple[str, str]] = set()
    _SEEDED_ALLOYS = (
        "mild_steel",
        "stainless_steel_304",
        "aluminium_6061",
        "brass",
    )
    # Loose alias map — the LLM might say "brass", "polished brass",
    # "stainless 304", "aluminium" etc. We normalise into our alloy slugs.
    _METAL_ALIASES = {
        "stainless steel": "stainless_steel_304",
        "stainless_steel": "stainless_steel_304",
        "stainless": "stainless_steel_304",
        "ss304": "stainless_steel_304",
        "mild steel": "mild_steel",
        "carbon steel": "mild_steel",
        "steel": "mild_steel",
        "aluminium": "aluminium_6061",
        "aluminum": "aluminium_6061",
        "al 6061": "aluminium_6061",
        "brass": "brass",
    }

    for obj in data.get("objects", []) or []:
        material_name = (obj.get("material") or "").strip().lower()
        if not material_name:
            continue
        alloy: str | None = None
        for seeded in _SEEDED_ALLOYS:
            if seeded.replace("_", " ") in material_name or seeded in material_name:
                alloy = seeded
                break
        if alloy is None:
            for alias, slug in _METAL_ALIASES.items():
                if alias in material_name:
                    alloy = slug
                    break
        if alloy is None:
            continue

        spec = await _get_metal_db(session, alloy=alloy)
        if not spec:
            continue
        obj_id = obj.get("id", "?")
        for prop in _METAL_PROPERTIES:
            value = spec.get(prop)
            if value is None:
                continue
            # ``yield_mpa`` may be a 2-tuple band stored as list — pick
            # the midpoint as the value-to-check so the per-alloy band
            # is compared against the BRD per-family band correctly.
            if isinstance(value, list):
                if len(value) != 2:
                    continue
                value = (float(value[0]) + float(value[1])) / 2.0
            if (alloy, prop) in _metal_already_warned:
                continue
            res = await _check_metal_property_db(
                session,
                alloy=alloy,
                property_key=prop,
                value=float(value),
                jurisdiction=jurisdiction,
            )
            if res.get("status") in {"warn_low", "warn_high"}:
                _metal_already_warned.add((alloy, prop))
                report["warnings"].append(
                    {
                        "code": "MATERIAL_OUT_OF_BRD_BAND",
                        "path": f"objects[{obj_id}].material",
                        "message": res["message"],
                        "reference": res.get("reference"),
                        "source_section": res.get("source_section"),
                        "jurisdiction": res.get("jurisdiction_used") or jurisdiction,
                    }
                )

    # ── Upholstery (BRD §1C — Leather / Fabric / Foam).
    # Most LLM-generated graphs name a material like "leather", "linen"
    # or "HD36 foam" without explicit thickness / durability / colour-
    # fastness numbers. The validator's job here is twofold:
    #   1. WARN — when the graph explicitly carries an out-of-band
    #      property (rare today, future-proof when graph schema grows).
    #   2. INFO suggestion — once per upholstery family seen, surface
    #      the BRD reference so the architect knows what they're meeting.
    # Foam density check is deliberately omitted — BRD's 180 kg/m³
    # disagrees with commercial reality (~36 kg/m³ for HD36).
    _upholstery_families_seen: set[str] = set()

    def _matches_any(s: str, needles: tuple[str, ...]) -> bool:
        return any(n in s for n in needles)

    upholstery_band: dict | None = None  # lazy-load on first match
    for obj in data.get("objects", []) or []:
        material_name = (obj.get("material") or "").strip().lower()
        if not material_name:
            continue
        family: str | None = None
        if _matches_any(material_name, ("leather",)):
            family = "leather"
        elif _matches_any(
            material_name,
            ("cotton", "linen", "wool", "synthetic", "performance poly", "polyester", "fabric"),
        ):
            family = "fabric"
        elif _matches_any(material_name, ("foam", "hd36", "hr40", "memory foam")):
            family = "foam"
        if family is None:
            continue

        # Hard-warn check: graph may carry explicit numeric fields like
        # ``thickness_mm`` (leather), ``durability_rubs_k``, or
        # ``cost_inr_m2`` we can validate against the BRD band. Skip if
        # absent — most graphs lack these.
        meta = obj.get("metadata") or {}
        obj_id = obj.get("id", "?")
        for prop in ("thickness_mm", "cost_inr_m2"):
            value = meta.get(prop)
            if value is None or family == "foam":
                continue
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                continue
            res = await _check_upholstery_property_db(
                session,
                family=family,
                property_key=prop,
                value=value_f,
                jurisdiction=jurisdiction,
            )
            if res.get("status") in {"warn_low", "warn_high"}:
                report["warnings"].append(
                    {
                        "code": "MATERIAL_OUT_OF_BRD_BAND",
                        "path": f"objects[{obj_id}].metadata.{prop}",
                        "message": res["message"],
                        "reference": res.get("reference"),
                        "source_section": res.get("source_section"),
                        "jurisdiction": res.get("jurisdiction_used") or jurisdiction,
                    }
                )

        rubs_k = meta.get("durability_rubs_k")
        if isinstance(rubs_k, (int, float)):
            is_commercial = segment == "commercial"
            res = await _check_upholstery_durability_db(
                session,
                rubs_k=float(rubs_k),
                is_commercial=is_commercial,
                jurisdiction=jurisdiction,
            )
            if res.get("status") in {"warn_low", "warn_high"}:
                report["warnings"].append(
                    {
                        "code": "MATERIAL_OUT_OF_BRD_BAND",
                        "path": f"objects[{obj_id}].metadata.durability_rubs_k",
                        "message": res["message"],
                        "reference": res.get("reference"),
                        "source_section": res.get("source_section"),
                        "jurisdiction": res.get("jurisdiction_used") or jurisdiction,
                    }
                )

        # INFO once per family — surfaces the BRD reference so the
        # architect knows what the catalogue says about this material.
        if family in _upholstery_families_seen:
            continue
        _upholstery_families_seen.add(family)
        if upholstery_band is None:
            upholstery_band = await _get_upholstery_brd_band_db(
                session, jurisdiction=jurisdiction
            )
        if not upholstery_band:
            continue
        sub = upholstery_band.get(family) or {}
        if family == "leather":
            grades = sub.get("grades") or []
            thickness = sub.get("thickness_mm") or []
            cost = sub.get("cost_inr_m2") or []
            note = (
                f"Leather options per BRD §1C: grades {'/'.join(grades) or '-'}; "
                f"thickness {thickness}; cost ₹{cost} /m²."
            )
        elif family == "fabric":
            types = sub.get("types") or []
            cost = sub.get("cost_inr_m2") or []
            note = (
                f"Fabric options per BRD §1C: {', '.join(types) or '-'}; "
                f"cost ₹{cost} /m²."
            )
        else:  # foam
            grade = sub.get("grade") or "-"
            density = sub.get("density_kg_m3")
            cost = sub.get("cost_inr_m3") or []
            note = (
                f"Foam per BRD §1C: {grade}, density {density} kg/m³, cost ₹{cost} /m³. "
                f"BRD value disagrees with commercial reality — see standard notes."
            )
        report["suggestions"].append(
            {
                "code": "UPHOLSTERY_REFERENCE",
                "path": f"objects[{obj.get('id','?')}].material",
                "message": note,
                "reference": "BRD §1C upholstery envelope",
                "source_section": "BRD §1C — Material physical properties",
                "jurisdiction": jurisdiction,
            }
        )

    # ── Upholstery Assembly manufacturing constraints (BRD §1C).
    # Once per generation when any upholstery family (leather, fabric,
    # foam) was detected above. Surfaces foam tolerance + webbing
    # tension + stitch density + QC checks + post-frame lead time from
    # ``mfg_process_spec_upholstery_detail``.
    if _upholstery_families_seen:
        detail_row = await _resolve_standard_db(
            session,
            slug="mfg_process_spec_upholstery_detail",
            category="manufacturing",
            jurisdiction=jurisdiction,
        )
        lead_row = await _resolve_standard_db(
            session,
            slug="mfg_lead_time_upholstery_post_frame",
            category="manufacturing",
            jurisdiction=jurisdiction,
        )
        if detail_row:
            dd = detail_row.get("data") or {}
            foam_tol = dd.get("foam_tolerance_mm")
            webbing = dd.get("webbing_tension_kg_per_inch")
            stitch = dd.get("stitch_density_per_inch")
            qc_checks = dd.get("qc_checks") or []
            lead = (lead_row or {}).get("data") or {}
            lt_low = lead.get("weeks_low")
            lt_high = lead.get("weeks_high")
            bits: list[str] = []
            if foam_tol is not None:
                bits.append(f"foam cut ±{foam_tol}mm")
            if isinstance(webbing, list) and len(webbing) == 2:
                bits.append(f"webbing tension {webbing[0]}–{webbing[1]} kg/in")
            if isinstance(stitch, list) and len(stitch) == 2:
                bits.append(f"stitch density {stitch[0]}–{stitch[1]} per inch")
            if lt_low is not None and lt_high is not None:
                bits.append(f"post-frame lead time {lt_low}–{lt_high} weeks")
            if qc_checks:
                qc_names = ", ".join(
                    str(c.get("check") if isinstance(c, dict) else c).replace("_", " ")
                    for c in qc_checks
                )
                bits.append(f"QC: {qc_names}")
            if bits:
                report["suggestions"].append(
                    {
                        "code": "MFG_UPHOLSTERY_ASSEMBLY_REFERENCE",
                        "path": "upholstery_assembly",
                        "message": (
                            "Upholstery assembly per BRD §1C: "
                            + "; ".join(bits)
                            + "."
                        ),
                        "reference": detail_row.get("notes")
                        or detail_row.get("display_name"),
                        "source_section": detail_row.get("source_section"),
                        "jurisdiction": detail_row.get("jurisdiction") or jurisdiction,
                    }
                )

    # ── Finishes & coatings (BRD §1C — DB-backed).
    # Detect known finish strings on object.material or
    # object.metadata.finish. Once-per-finish INFO surface with
    # citation + the row's thickness / coats / cost data so the
    # architect can verify the spec at a glance. Skip per-object
    # WARN checks — graphs don't carry per-object finish thickness
    # in practice (same dormant-until-graph-schema pattern as
    # accessibility ramps and fire egress paths).
    _finish_aliases = {
        # Lacquer
        "lacquer": "lacquer_pu",
        "lacquer pu": "lacquer_pu",
        "polyurethane": "lacquer_pu",
        "pu finish": "lacquer_pu",
        # Melamine + wax-oil
        "melamine": "melamine",
        "wax oil": "wax_oil",
        "wax-oil": "wax_oil",
        "wax_oil": "wax_oil",
        # Powder coat
        "powder coat": "powder_coat",
        "powder_coat": "powder_coat",
        "powdercoat": "powder_coat",
        # Anodise
        "anodise": "anodise",
        "anodize": "anodise",
        "anodised": "anodise",
        "anodized": "anodise",
        # BRD §1C completion (migration 0034)
        "oil varnish": "varnish_oil_based",
        "oil-based varnish": "varnish_oil_based",
        "varnish oil": "varnish_oil_based",
        "water varnish": "varnish_water_based",
        "water-based varnish": "varnish_water_based",
        "varnish water": "varnish_water_based",
        "varnish": "varnish_oil_based",  # default — oil-based has the richer film
        "stain": "stain",
        "wood stain": "stain",
        "leather care": "leather_care",
        "leather oil": "leather_care",
        "leather wax": "leather_care",
        "leather conditioner": "leather_care",
        "uv protect": "leather_care",
        "uv protection": "leather_care",
    }

    _finish_seen: set[str] = set()
    for obj in data.get("objects", []) or []:
        meta = obj.get("metadata") or {}
        # Two surfaces: explicit metadata.finish field, or finish word
        # baked into the material string (e.g. "walnut with PU lacquer").
        candidates: list[str] = []
        finish_meta = meta.get("finish")
        if isinstance(finish_meta, str) and finish_meta.strip():
            candidates.append(finish_meta.strip().lower())
        material_name = (obj.get("material") or "").strip().lower()
        if material_name:
            candidates.append(material_name)

        finish_slug: str | None = None
        for cand in candidates:
            # Direct slug match first (already-normalised input).
            for k in _KNOWN_FINISHES:
                if k in cand:
                    finish_slug = k
                    break
            if finish_slug is None:
                # Alias fallback (e.g. "lacquer" → "lacquer_pu",
                # "anodize" → "anodise").
                for alias, slug in _finish_aliases.items():
                    if alias in cand:
                        finish_slug = slug
                        break
            if finish_slug:
                break
        if finish_slug is None or finish_slug in _finish_seen:
            continue
        _finish_seen.add(finish_slug)

        row = await _resolve_finish_row_db(
            session, finish=finish_slug, jurisdiction=jurisdiction
        )
        if not row:
            continue
        d = row.get("data") or {}
        thickness = d.get("thickness_microns")
        cost = d.get("cost_inr_m2")
        coats = d.get("coats")
        cure_temp = d.get("cure_temp_c")
        cure_time = d.get("cure_time_min")
        parts: list[str] = []
        if thickness:
            parts.append(f"thickness {thickness} μm")
        if coats:
            parts.append(f"coats {coats}")
        # Powder coat carries cure parameters per BRD §1C (10-15 min
        # at 200°C). Surface them when present.
        if cure_temp is not None and cure_time is not None:
            parts.append(f"cure {cure_time} min @ {cure_temp}°C")
        if cost:
            parts.append(f"cost ₹{cost} /m²")
        spec_summary = "; ".join(parts) if parts else "spec available"
        note = f"Finish {finish_slug.replace('_', ' ')} per BRD §1C: {spec_summary}."

        report["suggestions"].append(
            {
                "code": "FINISH_REFERENCE",
                "path": f"objects[{obj.get('id','?')}].metadata.finish",
                "message": note,
                "reference": row.get("notes") or row.get("display_name"),
                "source_section": row.get("source_section"),
                "jurisdiction": row.get("jurisdiction") or jurisdiction,
            }
        )

    # ── Manufacturing constraints (BRD §1C — Woodworking + Metal fab).
    # Strip the sync versions of these suggestions so they don't double
    # up with the cited DB-backed equivalents below.
    _MFG_CODES = {
        "MFG_LEAD_TIME_WOOD",
        "MFG_LEAD_TIME_METAL",
        "MFG_TOLERANCE_PRECISION",
    }
    report["suggestions"] = [
        s for s in report.get("suggestions", []) if s.get("code") not in _MFG_CODES
    ]

    _WOOD_SPECIES_HINTS = ("walnut", "oak", "teak", "rosewood", "rubberwood")
    _METAL_HINTS = ("steel", "iron", "brass", "aluminium", "aluminum")

    _mfg_already_warned: set[str] = set()
    _wood_joinery_info_emitted = False

    for obj in data.get("objects", []) or []:
        mat_name = (obj.get("material") or "").lower()
        otype = (obj.get("type") or "").lower()
        meta = obj.get("metadata") or {}
        obj_id = obj.get("id", "?")

        # ── Wood lead-time (BRD §1C: 4-8 weeks) ─────────────────────
        if any(species in mat_name for species in _WOOD_SPECIES_HINTS):
            key = "lt_wood"
            if key not in _mfg_already_warned:
                _mfg_already_warned.add(key)
                lt = await _mfg_lead_time_for_db(session, "woodworking_furniture")
                row = await _resolve_standard_db(
                    session,
                    slug="mfg_lead_time_woodworking_furniture",
                    category="manufacturing",
                    jurisdiction=jurisdiction,
                )
                if lt and row:
                    report["suggestions"].append(
                        {
                            "code": "MFG_LEAD_TIME_WOOD",
                            "path": f"objects[{obj_id}].material",
                            "message": (
                                f"Solid-wood '{otype}' typically runs "
                                f"{lt[0]}-{lt[1]} weeks end-to-end."
                            ),
                            "reference": row.get("notes") or row.get("display_name"),
                            "source_section": row.get("source_section"),
                            "jurisdiction": row.get("jurisdiction") or jurisdiction,
                        }
                    )

            # Joinery options INFO — once per generation when wood furniture
            # is detected. Surfaces the BRD-allowed joinery palette so the
            # architect knows mortise-tenon / dovetail / pocket-hole apply.
            if not _wood_joinery_info_emitted:
                _wood_joinery_info_emitted = True
                spec_row = await _resolve_standard_db(
                    session,
                    slug="mfg_process_spec_woodworking",
                    category="manufacturing",
                    jurisdiction=jurisdiction,
                )
                if spec_row:
                    joinery_core = (spec_row.get("data") or {}).get("joinery_core") or []
                    moq_pieces = (spec_row.get("data") or {}).get("moq_pieces")
                    bits: list[str] = []
                    if joinery_core:
                        bits.append(
                            "joinery: " + ", ".join(
                                j.replace("_", "-") for j in joinery_core
                            )
                        )
                    if moq_pieces:
                        bits.append(f"MOQ {moq_pieces} piece (small-batch friendly)")
                    if bits:
                        report["suggestions"].append(
                            {
                                "code": "MFG_WOODWORKING_REFERENCE",
                                "path": f"objects[{obj_id}].material",
                                "message": (
                                    "Woodworking constraints per BRD §1C: "
                                    + "; ".join(bits)
                                    + "."
                                ),
                                "reference": spec_row.get("notes")
                                or spec_row.get("display_name"),
                                "source_section": spec_row.get("source_section"),
                                "jurisdiction": spec_row.get("jurisdiction")
                                or jurisdiction,
                            }
                        )

        # ── Metal lead-time (BRD §1C: 6-10 weeks per DB row) ────────
        if any(metal in mat_name for metal in _METAL_HINTS):
            key = "lt_metal"
            if key not in _mfg_already_warned:
                _mfg_already_warned.add(key)
                lt = await _mfg_lead_time_for_db(session, "metal_fabrication")
                row = await _resolve_standard_db(
                    session,
                    slug="mfg_lead_time_metal_fabrication",
                    category="manufacturing",
                    jurisdiction=jurisdiction,
                )
                if lt and row:
                    report["suggestions"].append(
                        {
                            "code": "MFG_LEAD_TIME_METAL",
                            "path": f"objects[{obj_id}].material",
                            "message": (
                                f"Metal fabrication for '{otype}' typically "
                                f"runs {lt[0]}-{lt[1]} weeks."
                            ),
                            "reference": row.get("notes") or row.get("display_name"),
                            "source_section": row.get("source_section"),
                            "jurisdiction": row.get("jurisdiction") or jurisdiction,
                        }
                    )

            # ── Metal fabrication reference INFO (BRD §1C) ─────────────
            # Once per generation when metal detected. Surfaces welding
            # palette + bending rule + structural/cosmetic tolerances
            # from a single seeded process-spec row.
            ref_key = "metalwork_reference"
            if ref_key not in _mfg_already_warned:
                _mfg_already_warned.add(ref_key)
                spec_row = await _resolve_standard_db(
                    session,
                    slug="mfg_process_spec_metal_fabrication",
                    category="manufacturing",
                    jurisdiction=jurisdiction,
                )
                if spec_row:
                    d = spec_row.get("data") or {}
                    welds = d.get("structural_welding") or []
                    bending = d.get("bending_radius_rule")
                    tol_s = d.get("tolerance_structural_mm")
                    tol_c = d.get("tolerance_cosmetic_mm")
                    bits: list[str] = []
                    if welds:
                        bits.append(
                            "structural welding: "
                            + " / ".join(w.replace("_", " ") for w in welds)
                        )
                    if bending:
                        bits.append(f"bending {bending}")
                    if tol_s is not None and tol_c is not None:
                        bits.append(
                            f"tolerance ±{tol_s}mm structural / ±{tol_c}mm cosmetic"
                        )
                    if bits:
                        report["suggestions"].append(
                            {
                                "code": "MFG_METALWORK_REFERENCE",
                                "path": f"objects[{obj_id}].material",
                                "message": (
                                    "Metal fabrication constraints per BRD §1C: "
                                    + "; ".join(bits)
                                    + "."
                                ),
                                "reference": spec_row.get("notes")
                                or spec_row.get("display_name"),
                                "source_section": spec_row.get("source_section"),
                                "jurisdiction": spec_row.get("jurisdiction")
                                or jurisdiction,
                            }
                        )

            # ── Bending radius check (BRD §1C: R_min ≥ 2.5 × thickness) ─
            # Fires only when the graph carries both ``thickness_mm`` and
            # ``bending_radius_mm`` in metadata — dormant until graph
            # schema evolves, same pattern as accessibility / fire egress.
            t_mm = meta.get("thickness_mm")
            r_mm = meta.get("bending_radius_mm")
            if isinstance(t_mm, (int, float)) and isinstance(r_mm, (int, float)) and t_mm > 0:
                ratio = float(r_mm) / float(t_mm)
                if ratio < 2.5:
                    bend_row = await _resolve_standard_db(
                        session,
                        slug="mfg_bending_rule",
                        category="manufacturing",
                        jurisdiction=jurisdiction,
                    )
                    report["warnings"].append(
                        {
                            "code": "MFG_BENDING_RADIUS_TIGHT",
                            "path": f"objects[{obj_id}].metadata.bending_radius_mm",
                            "message": (
                                f"Bending R={r_mm}mm on t={t_mm}mm gives R/t={ratio:.2f}; "
                                f"BRD §1C minimum is 2.5 — tighter risks cracking."
                            ),
                            "reference": (bend_row or {}).get("notes")
                            or (bend_row or {}).get("display_name"),
                            "source_section": (bend_row or {}).get("source_section"),
                            "jurisdiction": (bend_row or {}).get("jurisdiction")
                            or jurisdiction,
                        }
                    )

        # ── Precision tolerance hint (BRD §1C: ±0.5mm CNC) ─────────
        if meta.get("precision") == "high":
            key = f"tol_precision_{obj_id}"
            if key not in _mfg_already_warned:
                _mfg_already_warned.add(key)
                tol = await _mfg_tolerance_for_db(session, "woodworking_precision")
                row = await _resolve_standard_db(
                    session,
                    slug="mfg_tolerance_woodworking_precision",
                    category="manufacturing",
                    jurisdiction=jurisdiction,
                )
                if tol is not None and row:
                    report["suggestions"].append(
                        {
                            "code": "MFG_TOLERANCE_PRECISION",
                            "path": f"objects[{obj_id}].metadata.precision",
                            "message": (
                                f"Precision marked high — holds ±{tol}mm; "
                                "confirm CNC capability."
                            ),
                            "reference": row.get("notes") or row.get("display_name"),
                            "source_section": row.get("source_section"),
                            "jurisdiction": row.get("jurisdiction") or jurisdiction,
                        }
                    )

    # ── Quality Gates (BRD §1C) — DB-backed 5-stage QA roll-up.
    # Once per generation when any furniture-bearing object is present.
    # Surfaces the BRD canonical stage order with per-stage checks so the
    # architect sees the full acceptance criteria with citation. Same
    # dormant-until-graph-schema pattern as ramps and fire egress — we
    # can't validate per-object pass/fail without graph QC fields.
    if any(
        obj.get("type") or obj.get("material") for obj in (data.get("objects") or [])
    ):
        qa_rows = await _mfg_list_qa_gates_db(session, jurisdiction=jurisdiction)
        if qa_rows:
            stage_bits: list[str] = []
            for row in qa_rows:
                d = row.get("data") or {}
                stage = (d.get("stage") or "").replace("_", " ")
                scope = d.get("brd_scope") or ""
                if stage:
                    stage_bits.append(
                        f"{stage} ({scope})" if scope else stage
                    )
            if stage_bits:
                # Cite the rollup spec row so the architect can trace
                # both the canonical order and the per-stage checks.
                spec_row = await _resolve_standard_db(
                    session,
                    slug="mfg_quality_gates_brd_spec",
                    category="manufacturing",
                    jurisdiction=jurisdiction,
                )
                src_section = (
                    (spec_row or {}).get("source_section")
                    or (qa_rows[0].get("source_section"))
                )
                src_jur = (
                    (spec_row or {}).get("jurisdiction")
                    or (qa_rows[0].get("jurisdiction"))
                    or jurisdiction
                )
                report["suggestions"].append(
                    {
                        "code": "MFG_QUALITY_GATES_REFERENCE",
                        "path": "manufacturing.quality_gates",
                        "message": (
                            "Quality gates per BRD §1C: "
                            + " → ".join(stage_bits)
                            + "."
                        ),
                        "reference": (spec_row or {}).get("notes")
                        or (spec_row or {}).get("display_name")
                        or "BRD §1C Quality Gates",
                        "source_section": src_section,
                        "jurisdiction": src_jur,
                    }
                )

    # ── MEP (BRD §1B) — DB-backed HVAC + Lighting with citations.
    # Strip the sync versions of these suggestions so they don't double up
    # with the cited DB-backed equivalents below.
    _MEP_CODES = {"HVAC_FRESH_AIR_TARGET", "LIGHTING_POWER_TARGET"}
    report["suggestions"] = [
        s for s in report.get("suggestions", []) if s.get("code") not in _MEP_CODES
    ]

    # Re-derive room dims as metres (validator runs on graphs that may
    # store dims in mm or m — _to_m handles both).
    room_length_m = _to_m(dims.get("length")) if dims else None
    room_width_m = _to_m(dims.get("width")) if dims else None
    room_height_m = _to_m(dims.get("height")) if dims else None

    if room_length_m and room_width_m and room_height_m:
        area_m2 = room_length_m * room_width_m
        volume_m3 = area_m2 * room_height_m

        # HVAC fresh-air target. Skip silently if the room type isn't in the
        # mep_hvac_ach_* seed (uncommon room types just get no suggestion).
        cfm_res = await _hvac_cfm_db(
            session,
            room_volume_m3=volume_m3,
            use_type=room_type,
            jurisdiction=jurisdiction,
        )
        if "error" not in cfm_res:
            hvac_row = await _resolve_standard_db(
                session,
                slug=f"mep_hvac_ach_{room_type}",
                category="mep",
                jurisdiction=jurisdiction,
            )
            report["suggestions"].append(
                {
                    "code": "HVAC_FRESH_AIR_TARGET",
                    "path": "room.dimensions",
                    "message": (
                        f"Plan fresh-air supply around {cfm_res['cfm_total']} CFM "
                        f"({cfm_res['ach']} ACH × {volume_m3:.1f} m³)."
                    ),
                    "reference": (hvac_row or {}).get("notes")
                    or (hvac_row or {}).get("display_name"),
                    "source_section": (hvac_row or {}).get("source_section"),
                    "jurisdiction": (hvac_row or {}).get("jurisdiction")
                    or jurisdiction,
                }
            )

        # Lighting power target — same closed vocabulary as the legacy
        # sync version (residential / office_general / restaurant / retail).
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
        lp_res = await _lighting_circuits_db(
            session, area_m2=area_m2, use=use_profile, jurisdiction=jurisdiction
        )
        light_row = await _resolve_standard_db(
            session,
            slug=f"mep_elec_power_density_{use_profile}",
            category="mep",
            jurisdiction=jurisdiction,
        )
        report["suggestions"].append(
            {
                "code": "LIGHTING_POWER_TARGET",
                "path": "room.dimensions",
                "message": (
                    f"Lighting load ~{lp_res['total_load_w']}W "
                    f"(density {lp_res['density_w_m2']} W/m²) "
                    f"— plan {lp_res['lighting_circuits']} dedicated lighting circuit(s)."
                ),
                "reference": (light_row or {}).get("notes")
                or (light_row or {}).get("display_name"),
                "source_section": (light_row or {}).get("source_section"),
                "jurisdiction": (light_row or {}).get("jurisdiction") or jurisdiction,
            }
        )

    # Rebuild the summary line so the counts stay accurate after the swap.
    report["ok"] = len(report.get("errors", [])) == 0
    report["summary"] = (
        f"{len(report.get('errors', []))} error(s), "
        f"{len(report.get('warnings', []))} warning(s), "
        f"{len(report.get('suggestions', []))} suggestion(s)."
    )
    return report
