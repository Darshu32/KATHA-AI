"""Project drawing helpers for turning saved design graphs into floor-plan outputs."""

from __future__ import annotations

from html import escape

from app.services import drawing_engine
from app.services.spatial.graph_geometry import (
    furnishable_objects,
    object_rect,
    placed_spaces,
    room_id,
    room_name,
    room_rect,
)

SVG_PADDING = 56
SVG_WIDTH = 960
SVG_HEIGHT = 640


def generate_floor_plan_package(graph_data: dict) -> dict:
    """Build a structured floor plan plus an SVG preview from a design graph snapshot."""
    drawing = drawing_engine.process(
        _build_input_data(graph_data),
        _build_theme_config(graph_data),
        _build_concept_data(graph_data),
        _build_layout_data(graph_data),
    )
    return {
        "drawing_type": "floor_plan",
        "floor_plan": drawing["floor_plan"],
        "drawing": drawing,
        # Multi-room-aware preview: draws EVERY placed room + its furniture in
        # world coords. The legacy single-room render_floor_plan_svg collapsed
        # multi-room plans into one box with all furniture clamped/overlapping.
        "preview_svg": render_multiroom_plan_svg(graph_data),
        "summary": _build_summary(graph_data, drawing),
    }


def render_multiroom_plan_svg(graph_data: dict) -> str:
    """Floor-plan preview that renders EVERY placed room (walls + name + area),
    furniture in world coordinates inside each room, and doors on the walls that
    adjacent rooms share. Falls back to a single-room shell. Replaces the legacy
    single-room renderer that collapsed multi-room plans into one box."""
    W, H, PAD = SVG_WIDTH, SVG_HEIGHT, SVG_PADDING

    # Rooms and furniture come from the shared geometry core (graph_geometry) —
    # the same placed-space rule and object footprints every other working
    # drawing projects from. Fall back to the first dimensioned room as an
    # unplaced shell so an un-solved graph still previews something.
    spaces = placed_spaces(graph_data)
    if not spaces:
        spaces = [s for s in (graph_data.get("spaces") or [])
                  if isinstance(s, dict) and isinstance(s.get("dimensions"), dict)][:1]
    rooms: list[dict] = []
    for i, s in enumerate(spaces):
        r = room_rect(s)
        if (r.x1 - r.x0) <= 0 or (r.z1 - r.z0) <= 0:
            continue
        rooms.append({
            "id": room_id(s, i),
            "name": room_name(s, i),
            "x": r.x0, "z": r.z0, "l": r.x1 - r.x0, "w": r.z1 - r.z0,
        })
    if not rooms:
        return _empty_plan_svg()

    furn: list[dict] = []
    for o in furnishable_objects(graph_data):
        r = object_rect(o)
        furn.append({
            "type": str(o.get("type") or "item").replace("_", " "),
            "x": (r.x0 + r.x1) / 2, "z": (r.z0 + r.z1) / 2,
            "l": r.x1 - r.x0, "w": r.z1 - r.z0,
        })

    xs = [r["x"] for r in rooms] + [r["x"] + r["l"] for r in rooms]
    zs = [r["z"] for r in rooms] + [r["z"] + r["w"] for r in rooms]
    minx, maxx, minz, maxz = min(xs), max(xs), min(zs), max(zs)
    vbW, vbH = (maxx - minx) or 1.0, (maxz - minz) or 1.0
    scale = min((W - 2 * PAD) / vbW, (H - 2 * PAD) / vbH)
    ox = PAD + (W - 2 * PAD - vbW * scale) / 2
    oy = PAD + (H - 2 * PAD - vbH * scale) / 2

    def mp(x: float, z: float) -> tuple[float, float]:
        return ox + (x - minx) * scale, oy + (z - minz) * scale

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" fill="none">',
        '<rect width="100%" height="100%" fill="#fcf7ef"/>',
        f'<text x="{PAD}" y="32" fill="#7d6b58" font-size="16" font-weight="700">Generated Floor Plan</text>',
    ]
    for r in rooms:
        x, y = mp(r["x"], r["z"])
        w, h = r["l"] * scale, r["w"] * scale
        cx = x + w / 2
        nfs = min(13.0, max(8.0, (w * 0.9) / max(len(r["name"]) * 0.55, 1)))
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="#fbf7f0" stroke="#4c3d30" stroke-width="4" stroke-linejoin="round"/>')
        out.append(f'<text x="{cx:.1f}" y="{y + nfs + 4:.1f}" text-anchor="middle" fill="#2c221a" font-size="{nfs:.1f}" font-weight="700">{escape(r["name"][:22])}</text>')
        out.append(f'<text x="{cx:.1f}" y="{y + nfs * 2 + 6:.1f}" text-anchor="middle" fill="#9d8a75" font-size="{nfs * 0.8:.1f}">{r["l"] * r["w"]:.1f} m²</text>')
    for f in furn:
        x, y = mp(f["x"] - f["l"] / 2, f["z"] - f["w"] / 2)
        w, h = f["l"] * scale, f["w"] * scale
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="4" fill="#d9c7b1" stroke="#8a7357" stroke-width="1.5"/>')
        lbl = f["type"][:16]
        fs = min(11.0, (w * 0.9) / max(len(lbl) * 0.55, 1), h * 0.6)
        if fs >= 6.0:
            out.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + fs * 0.35:.1f}" text-anchor="middle" fill="#3f3f46" font-size="{fs:.1f}">{escape(lbl)}</text>')
    rmap = {r["id"]: r for r in rooms}
    eps = 0.35
    for adj in (graph_data.get("adjacencies") or []):
        if not isinstance(adj, dict):
            continue
        a, b = rmap.get(str(adj.get("a"))), rmap.get(str(adj.get("b")))
        if not a or not b:
            continue
        door = None
        if abs((a["x"] + a["l"]) - b["x"]) < eps or abs((b["x"] + b["l"]) - a["x"]) < eps:
            wx = a["x"] + a["l"] if abs((a["x"] + a["l"]) - b["x"]) < eps else a["x"]
            z0, z1 = max(a["z"], b["z"]), min(a["z"] + a["w"], b["z"] + b["w"])
            if z1 - z0 > 0.6:
                door = ("v", wx, (z0 + z1) / 2, min(0.9, z1 - z0 - 0.2))
        elif abs((a["z"] + a["w"]) - b["z"]) < eps or abs((b["z"] + b["w"]) - a["z"]) < eps:
            wz = a["z"] + a["w"] if abs((a["z"] + a["w"]) - b["z"]) < eps else a["z"]
            x0, x1 = max(a["x"], b["x"]), min(a["x"] + a["l"], b["x"] + b["l"])
            if x1 - x0 > 0.6:
                door = ("h", wz, (x0 + x1) / 2, min(0.9, x1 - x0 - 0.2))
        if not door:
            continue
        kind, fixed, center, size = door
        p1 = mp(fixed, center - size / 2) if kind == "v" else mp(center - size / 2, fixed)
        p2 = mp(fixed, center + size / 2) if kind == "v" else mp(center + size / 2, fixed)
        out.append(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" stroke="#fcf7ef" stroke-width="6"/>')
        out.append(f'<line x1="{p1[0]:.1f}" y1="{p1[1]:.1f}" x2="{p2[0]:.1f}" y2="{p2[1]:.1f}" stroke="#8b5e3c" stroke-width="2.5" stroke-dasharray="4 3"/>')
    out.append("</svg>")
    return "\n".join(out)


def _empty_plan_svg() -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" fill="none">'
            '<rect width="100%" height="100%" fill="#fcf7ef"/>'
            f'<text x="{SVG_WIDTH // 2}" y="{SVG_HEIGHT // 2}" text-anchor="middle" '
            'fill="#9d8a75" font-size="14">No placed rooms to draw yet.</text></svg>')


def _build_input_data(graph_data: dict) -> dict:
    space = _primary_space(graph_data)
    dimensions = dict(space.get("dimensions") or {})
    unit = dimensions.get("unit")
    if unit not in {"ft", "m"}:
        unit = "ft"

    return {
        "room_type": str(space.get("room_type") or space.get("name") or "space").strip().lower().replace(" ", "_"),
        "dimensions": {
            "length": float(dimensions.get("length") or 12),
            "width": float(dimensions.get("width") or 10),
            "height": float(dimensions.get("height") or 10),
            "unit": unit,
        },
    }


def _build_theme_config(graph_data: dict) -> dict:
    style = graph_data.get("style") or {}
    material_names = [
        str(material.get("name")).strip()
        for material in graph_data.get("materials", [])
        if isinstance(material, dict) and material.get("name")
    ]
    lighting_types = [
        str(light.get("type")).strip()
        for light in graph_data.get("lighting", [])
        if isinstance(light, dict) and light.get("type")
    ]

    return {
        "style": str(style.get("primary") or "modern").strip().lower(),
        "materials": material_names[:6],
        "lighting": ", ".join(lighting_types[:3]) or "balanced lighting",
    }


def _build_concept_data(graph_data: dict) -> dict:
    constraints = graph_data.get("constraints", [])
    prompt_fragments = [
        str(item.get("value")).strip()
        for item in constraints
        if isinstance(item, dict) and item.get("type") == "starter_prompt" and item.get("value")
    ]
    style = graph_data.get("style") or {}

    return {
        "design_intent": prompt_fragments[0] if prompt_fragments else f"Translate the {style.get('primary', 'current')} layout into a buildable floor plan.",
        "material_strategy": ", ".join(
            str(material.get("name")).strip()
            for material in graph_data.get("materials", [])[:4]
            if isinstance(material, dict) and material.get("name")
        ),
        "lighting_strategy": ", ".join(
            str(light.get("type")).strip()
            for light in graph_data.get("lighting", [])[:3]
            if isinstance(light, dict) and light.get("type")
        ) or "balanced lighting",
    }


def _build_layout_data(graph_data: dict) -> dict:
    input_data = _build_input_data(graph_data)
    dimensions = input_data["dimensions"]
    furniture = []

    for obj in graph_data.get("objects", []):
        if not isinstance(obj, dict):
            continue
        position = obj.get("position") or {}
        obj_dimensions = obj.get("dimensions") or {}
        furniture.append(
            {
                "id": obj.get("id") or f"object_{len(furniture) + 1}",
                "type": _normalize_object_type(str(obj.get("type") or "generic")),
                "zone": str(obj.get("zone") or "primary_area"),
                "orientation": str(obj.get("name") or obj.get("type") or "").strip(),
                "rotation": round(float((obj.get("rotation") or {}).get("y", 0) or 0)),
                "coordinates": {
                    "x": _clamp(float(position.get("x") or dimensions["length"] / 2), 0.0, dimensions["length"]),
                    "y": _clamp(float(position.get("z") or dimensions["width"] / 2), 0.0, dimensions["width"]),
                    "z": float(position.get("y") or 0),
                },
                "size": {
                    "width": max(float(obj_dimensions.get("width") or 2.0), 0.2),
                    "depth": max(float(obj_dimensions.get("length") or 2.0), 0.2),
                    "height": max(float(obj_dimensions.get("height") or 0.9), 0.2),
                },
                "clearance": {"front": 1.0, "back": 0.5, "left": 0.5, "right": 0.5},
            }
        )

    return {
        "room_type": input_data["room_type"],
        "dimensions": dimensions,
        "layout_summary": f"Auto-generated floor plan for {input_data['room_type']}.",
        "furniture": furniture,
        "zones": _build_zones(graph_data),
        "relationships": [],
        "grid": {"unit": 1.0, "snap": True},
        "spacing": {"walkways": "Maintain circulation around major furniture.", "furniture_gaps": "Auto-derived from object placement."},
        "theme_reference": _build_theme_config(graph_data),
    }


def render_floor_plan_svg(drawing: dict) -> str:
    """Render a lightweight SVG preview for the generated floor plan."""
    walls = drawing["floor_plan"]["walls"]
    doors = drawing["floor_plan"]["doors"]
    windows = drawing["floor_plan"]["windows"]
    furniture = drawing["floor_plan"]["furniture"]
    dimensions = drawing["canvas"]

    max_x = max(max(wall["start"]["x"], wall["end"]["x"]) for wall in walls)
    max_y = max(max(wall["start"]["y"], wall["end"]["y"]) for wall in walls)
    scale = min((SVG_WIDTH - SVG_PADDING * 2) / max(max_x, 1), (SVG_HEIGHT - SVG_PADDING * 2) / max(max_y, 1))

    def map_point(x: float, y: float) -> tuple[float, float]:
        px = SVG_PADDING + x * scale
        py = SVG_PADDING + y * scale
        return round(px, 2), round(py, 2)

    segments: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT}" fill="none">',
        '<rect width="100%" height="100%" rx="28" fill="#fcf7ef"/>',
        '<defs><pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M 24 0 L 0 0 0 24" stroke="#eadfce" stroke-width="1"/></pattern></defs>',
        f'<rect x="0" y="0" width="{SVG_WIDTH}" height="{SVG_HEIGHT}" fill="url(#grid)"/>',
        f'<text x="{SVG_PADDING}" y="34" fill="#7d6b58" font-size="16" font-weight="700">Generated Floor Plan</text>',
        f'<text x="{SVG_PADDING}" y="56" fill="#9d8a75" font-size="13">Unit: {escape(str(dimensions.get("unit", "ft")))}, Scale: {escape(str(drawing.get("scale", "1:50")))}</text>',
    ]

    for wall in walls:
        x1, y1 = map_point(wall["start"]["x"], wall["start"]["y"])
        x2, y2 = map_point(wall["end"]["x"], wall["end"]["y"])
        stroke_width = max(float(wall.get("thickness", 0.2)) * scale, 8)
        segments.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#4c3d30" stroke-width="{round(stroke_width, 2)}" stroke-linecap="round"/>'
        )

    for opening in windows:
        start = opening["line"][0]
        end = opening["line"][1]
        x1, y1 = map_point(start["x"], start["y"])
        x2, y2 = map_point(end["x"], end["y"])
        segments.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#96bfd0" stroke-width="7" stroke-linecap="round"/>'
        )

    for door in doors:
        start = door["line"][0]
        end = door["line"][1]
        x1, y1 = map_point(start["x"], start["y"])
        x2, y2 = map_point(end["x"], end["y"])
        segments.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#8b5e3c" stroke-width="5" stroke-linecap="round"/>'
        )

    for item in furniture:
        bbox = item["bbox"]
        x, y = map_point(bbox["min_x"], bbox["min_y"])
        width = round((bbox["max_x"] - bbox["min_x"]) * scale, 2)
        height = round((bbox["max_y"] - bbox["min_y"]) * scale, 2)
        label_x = x + width / 2
        label_y = y + height / 2 + 4
        segments.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="12" fill="#d9c7b1" stroke="#6d5743" stroke-width="2.5"/>'
        )
        segments.append(
            f'<text x="{round(label_x, 2)}" y="{round(label_y, 2)}" text-anchor="middle" fill="#2c221a" font-size="11" font-weight="600">{escape(str(item.get("type", "item")).replace("_", " ")[:18])}</text>'
        )

    for dimension in drawing["floor_plan"]["dimensions"]:
        x1, y1 = map_point(dimension["from"][0], dimension["from"][1])
        x2, y2 = map_point(dimension["to"][0], dimension["to"][1])
        label_x = round((x1 + x2) / 2, 2)
        label_y = round((y1 + y2) / 2 - 10, 2)
        segments.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#b8a591" stroke-width="2" stroke-dasharray="5 5"/>'
        )
        segments.append(
            f'<text x="{label_x}" y="{label_y}" text-anchor="middle" fill="#8b755f" font-size="12">{escape(str(dimension["label"]))}</text>'
        )

    segments.append("</svg>")
    return "".join(segments)


def _build_summary(graph_data: dict, drawing: dict) -> dict:
    return {
        "room_name": str(_primary_space(graph_data).get("name") or "Primary Space"),
        "object_count": len(graph_data.get("objects", [])),
        "wall_count": len(drawing["floor_plan"]["walls"]),
        "door_count": len(drawing["floor_plan"]["doors"]),
        "window_count": len(drawing["floor_plan"]["windows"]),
        "unit": drawing["canvas"].get("unit", "ft"),
        "scale": drawing.get("scale", "1:50"),
    }


def _build_zones(graph_data: dict) -> list[dict]:
    space = _primary_space(graph_data)
    return [
        {
            "name": str(space.get("name") or "primary_area").strip() or "primary_area",
            "purpose": str(space.get("room_type") or "main layout").strip(),
            "position": "center",
        }
    ]


def _primary_space(graph_data: dict) -> dict:
    spaces = graph_data.get("spaces", [])
    if spaces and isinstance(spaces[0], dict):
        return spaces[0]
    return {}


def _normalize_object_type(value: str) -> str:
    normalized = value.strip().lower()
    mapping = {
        "coffee_table": "coffee_table",
        "media_console": "console",
        "tv_unit": "tv_unit",
        "wall_art": "art",
        "floor_lamp": "lamp",
    }
    return mapping.get(normalized, normalized)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))
