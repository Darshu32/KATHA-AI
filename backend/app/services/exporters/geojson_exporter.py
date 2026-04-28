"""GeoJSON exporter — RFC 7946 FeatureCollection.

Each design object is a 2-D polygon Feature in the X/Z plane (top-down
plan view), with the full project metadata folded into properties:
material, finish, theme, manufacturing complexity, lead time band,
cost line items, and schedule. Drops cleanly into web mapping libraries
(Leaflet, Mapbox), GIS tools (QGIS, ArcGIS), and BIM platforms that
ingest GeoJSON for site / floorplan overlays.

The CRS is unscaled local metres (RFC 7946 §4 — `coordinates` are in
local Cartesian when geographic CRS is not declared). Every feature
carries a metric scale hint in `properties.units`.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone


def _m(value) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return v / 1000.0 if v > 20 else v


def _safe_name(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in (name or "project")).strip("-") or "project"


def _box_polygon(cx: float, cz: float, l: float, w: float) -> list[list[float]]:
    """Top-down rectangle as a closed RFC 7946 LinearRing (counter-clockwise)."""
    hx, hz = l / 2.0, w / 2.0
    return [
        [cx - hx, cz - hz],
        [cx + hx, cz - hz],
        [cx + hx, cz + hz],
        [cx - hx, cz + hz],
        [cx - hx, cz - hz],
    ]


def _material_index(graph: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for mat in graph.get("materials") or []:
        mid = mat.get("id") or mat.get("name")
        if not mid:
            continue
        out[mid] = {
            "name": mat.get("name") or mid,
            "color": mat.get("color"),
            "category": mat.get("category"),
            "supplier": mat.get("supplier"),
        }
    return out


def _cost_line_for_object(spec: dict, object_id: str) -> dict | None:
    items = ((spec.get("cost") or {}).get("line_items") or [])
    for item in items:
        if str(item.get("object_id") or item.get("id") or "") == str(object_id):
            return {
                "amount_inr": item.get("total_inr") or item.get("amount_inr"),
                "category": item.get("category"),
                "quantity": item.get("quantity"),
                "unit": item.get("unit"),
            }
    return None


def export(spec: dict, graph: dict) -> dict:
    meta = spec.get("meta") or {}
    project = _safe_name(meta.get("project_name", "project"))
    today = datetime.now(timezone.utc).isoformat(timespec="seconds")
    materials = _material_index(graph)
    manufacturing = spec.get("manufacturing") or {}
    mep = spec.get("mep") or {}
    cost = spec.get("cost") or {}

    features: list[dict] = []

    # Room footprint.
    room_dims = (graph.get("room") or {}).get("dimensions") or meta.get("dimensions_m") or {}
    room_l = float(room_dims.get("length") or 6.0)
    room_w = float(room_dims.get("width") or 5.0)
    room_h = float(room_dims.get("height") or 3.0)
    features.append({
        "type": "Feature",
        "id": "room",
        "geometry": {
            "type": "Polygon",
            "coordinates": [_box_polygon(room_l / 2.0, room_w / 2.0, room_l, room_w)],
        },
        "properties": {
            "kind": "room",
            "type": meta.get("room_type"),
            "theme": meta.get("theme"),
            "dimensions_m": {"length": room_l, "width": room_w, "height": room_h},
            "area_m2": round(room_l * room_w, 2),
            "volume_m3": round(room_l * room_w * room_h, 2),
            "units": "metres",
            "mep": {
                "ach_target": ((mep.get("hvac") or {}).get("ach_target")),
                "cfm_total": ((mep.get("hvac") or {}).get("cfm_fresh_air")),
                "main_drain_size_mm": ((mep.get("plumbing") or {}).get("main_drain_size_mm")),
            },
        },
    })

    # Each object.
    for obj in graph.get("objects") or []:
        otype = (obj.get("type") or "object").lower()
        oid = obj.get("id") or otype
        d = obj.get("dimensions") or {}
        pos = obj.get("position") or {}
        cx = float(pos.get("x", 0))
        cz = float(pos.get("z", 0))
        l = max(_m(d.get("length")) or 0.4, 0.05)
        w = max(_m(d.get("width")) or 0.4, 0.05)
        h = max(_m(d.get("height")) or 0.4, 0.05)
        mat_ref = obj.get("material")
        mat_props = materials.get(mat_ref) or {}
        cost_line = _cost_line_for_object(spec, oid)

        features.append({
            "type": "Feature",
            "id": str(oid),
            "geometry": {
                "type": "Polygon",
                "coordinates": [_box_polygon(cx, cz, l, w)],
            },
            "properties": {
                "kind": "object",
                "type": otype,
                "label": obj.get("label") or otype.replace("_", " ").title(),
                "dimensions_m": {"length": round(l, 3), "width": round(w, 3), "height": round(h, 3)},
                "footprint_m2": round(l * w, 3),
                "material_ref": mat_ref,
                "material": mat_props,
                "manufacturing": {
                    "complexity": (manufacturing.get("woodworking_notes") or {}).get("lead_time", {}).get("complexity")
                                  or (manufacturing.get("metal_fabrication_notes") or {}).get("lead_time", {}).get("complexity"),
                    "lead_time_weeks": (manufacturing.get("woodworking_notes") or {}).get("lead_time"),
                },
                "cost": cost_line,
                "units": "metres",
            },
        })

    fc = {
        "type": "FeatureCollection",
        "name": project,
        "metadata": {
            "project_name": meta.get("project_name"),
            "theme": meta.get("theme"),
            "generated_at": today,
            "currency": (cost.get("currency") or "INR"),
            "totals_inr": cost.get("totals"),
            "schedule_lead_time_weeks": (manufacturing.get("woodworking_notes") or {}).get("lead_time"),
            "exporter": "KATHA AI GeoJSON 5A",
            "spec_version": "RFC 7946",
            "axis_note": "X = floor length (m), Y = floor width (m); Y-up plan view, local Cartesian.",
        },
        "features": features,
    }

    body = json.dumps(fc, indent=2, ensure_ascii=False)
    return {
        "content_type": "application/geo+json",
        "filename": f"{project}-plan.geojson",
        "bytes": body.encode("utf-8"),
    }
