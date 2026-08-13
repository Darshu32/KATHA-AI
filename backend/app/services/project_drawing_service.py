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

# Warm-paper working-drawing palette (kept in step with the other preview sheets).
_PAPER = "#fcf7ef"      # sheet background
_FLOOR = "#fbf7f0"      # room floor fill
_INK = "#2c221a"        # primary line / leaf ink
_WALL = "#4c3d30"       # wall poché
_FURN_FILL = "#e7dbc8"  # furniture footprint fill (lighter than walls so walls read first)
_FURN_INK = "#8a7357"   # furniture outline
_DIM = "#b8a68e"        # dimension lines + witness ticks


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
    """Floor-plan preview: every placed room drawn with wall poché, its
    furniture clamped inside the room envelope, doors on shared walls (plus an
    entry door + swing for a lone room), overall dimension strings, a scale bar
    and a north arrow. Falls back to a single-room shell for an un-solved graph."""
    W, H = SVG_WIDTH, SVG_HEIGHT
    # Asymmetric margins reserve room for the title (top), the vertical
    # dimension string (left) and the horizontal dimension string + scale bar
    # (bottom). Symmetric padding used to clip the dimension annotations.
    M_L, M_R, M_T, M_B = 92, 66, 60, 96

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

    # Locate each piece's room (centre; nearest as fallback) and CLAMP its
    # footprint to that room's interior. A piece whose graph coordinates spill
    # past a wall is slid back inside; one larger than the room is capped to it.
    # This is what stops furniture being drawn straight through the walls.
    def _room_of(cx: float, cz: float) -> dict:
        for rm in rooms:
            if rm["x"] <= cx <= rm["x"] + rm["l"] and rm["z"] <= cz <= rm["z"] + rm["w"]:
                return rm
        return min(rooms, key=lambda rm: abs(cx - (rm["x"] + rm["l"] / 2)) + abs(cz - (rm["z"] + rm["w"] / 2)))

    furn: list[dict] = []
    for o in furnishable_objects(graph_data):
        r = object_rect(o)
        x0, x1, z0, z1 = r.x0, r.x1, r.z0, r.z1
        rm = _room_of((x0 + x1) / 2, (z0 + z1) / 2)
        m = 0.06  # keep a hair off the wall face so the piece reads as inside
        ix0, ix1 = rm["x"] + m, rm["x"] + rm["l"] - m
        iz0, iz1 = rm["z"] + m, rm["z"] + rm["w"] - m
        if x1 - x0 > ix1 - ix0:        # wider than the room → cap to interior
            x0, x1 = ix0, ix1
        elif x0 < ix0:                 # crosses the left/right wall → slide in
            x0, x1 = ix0, ix0 + (x1 - x0)
        elif x1 > ix1:
            x0, x1 = ix1 - (x1 - x0), ix1
        if z1 - z0 > iz1 - iz0:
            z0, z1 = iz0, iz1
        elif z0 < iz0:
            z0, z1 = iz0, iz0 + (z1 - z0)
        elif z1 > iz1:
            z0, z1 = iz1 - (z1 - z0), iz1
        furn.append({
            "type": str(o.get("type") or "item").replace("_", " "),
            "x": (x0 + x1) / 2, "z": (z0 + z1) / 2,
            "l": x1 - x0, "w": z1 - z0,
        })

    minx = min(r["x"] for r in rooms)
    minz = min(r["z"] for r in rooms)
    maxx = max(r["x"] + r["l"] for r in rooms)
    maxz = max(r["z"] + r["w"] for r in rooms)
    vbW, vbH = (maxx - minx) or 1.0, (maxz - minz) or 1.0
    aw, ah = (W - M_L - M_R), (H - M_T - M_B)
    scale = min(aw / vbW, ah / vbH)
    ox = M_L + (aw - vbW * scale) / 2
    oy = M_T + (ah - vbH * scale) / 2

    def mp(x: float, z: float) -> tuple[float, float]:
        return ox + (x - minx) * scale, oy + (z - minz) * scale

    wall = max(0.12 * scale, 5.0)  # ~120 mm wall, floored so the poché always reads

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" fill="none" '
        f'font-family="ui-sans-serif, system-ui, sans-serif">',
        f'<rect width="100%" height="100%" fill="{_PAPER}"/>',
        f'<text x="{M_L}" y="34" fill="#7d6b58" font-size="15" font-weight="700" '
        f'letter-spacing="0.08em">GENERATED FLOOR PLAN</text>',
    ]

    # Rooms — floor fill, then wall poché (a thick stroke straddling the edge).
    for r in rooms:
        x, y = mp(r["x"], r["z"])
        w, h = r["l"] * scale, r["w"] * scale
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{_FLOOR}"/>')
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="none" '
                   f'stroke="{_WALL}" stroke-width="{wall:.1f}" stroke-linejoin="miter"/>')

    # Furniture — clamped footprints with a hairline outline + fitted label.
    for f in furn:
        x, y = mp(f["x"] - f["l"] / 2, f["z"] - f["w"] / 2)
        w, h = f["l"] * scale, f["w"] * scale
        out.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="3" '
                   f'fill="{_FURN_FILL}" stroke="{_FURN_INK}" stroke-width="1.4"/>')
        lbl = f["type"][:16]
        fs = min(11.0, (w * 0.9) / max(len(lbl) * 0.55, 1), h * 0.6)
        if fs >= 6.0:
            out.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + fs * 0.35:.1f}" '
                       f'text-anchor="middle" fill="#5b5048" font-size="{fs:.1f}">{escape(lbl)}</text>')

    # Doors on the walls that two adjacent rooms share.
    rmap = {r["id"]: r for r in rooms}
    door_drawn = False
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
        door_drawn = True
        kind, fixed, center, size = door
        if kind == "v":
            out += _door_swing(mp, fixed, center - size / 2, "v", size, scale, wall)
        else:
            out += _door_swing(mp, center - size / 2, fixed, "h", size, scale, wall)

    # A lone room (or one with no shared-wall door) gets an entry door + swing
    # centred on its front (max-z) wall so the plan never reads as sealed.
    if not door_drawn:
        big = max(rooms, key=lambda r: r["l"] * r["w"])
        dw = min(0.9, big["l"] * 0.5)
        out += _door_swing(mp, big["x"] + big["l"] / 2 - dw / 2, big["z"] + big["w"], "h", dw, scale, wall)

    # Room name + area tag drawn LAST as a paper pill in the top-left corner.
    for r in rooms:
        x, y = mp(r["x"], r["z"])
        w = r["l"] * scale
        name = r["name"][:22]
        area = f'{r["l"] * r["w"]:.1f} m²'
        nfs = min(13.0, max(8.0, (w * 0.9) / max(len(name) * 0.55, 1)))
        tw = max(len(name) * nfs * 0.55, len(area) * nfs * 0.8 * 0.55) + 12
        lx, ly = x + wall / 2 + 5, y + wall / 2 + 5
        out.append(f'<rect x="{lx - 4:.1f}" y="{ly:.1f}" width="{tw:.1f}" height="{nfs * 2 + 12:.1f}" rx="3" fill="#fbf7f0" fill-opacity="0.92"/>')
        out.append(f'<text x="{lx:.1f}" y="{ly + nfs + 2:.1f}" fill="#2c221a" font-size="{nfs:.1f}" font-weight="700">{escape(name)}</text>')
        out.append(f'<text x="{lx:.1f}" y="{ly + nfs * 2 + 4:.1f}" fill="#9d8a75" font-size="{nfs * 0.8:.1f}">{escape(area)}</text>')

    # Overall dimension strings (width below, height at left) + scale bar + north.
    plan_l, plan_r = ox, ox + vbW * scale
    plan_t, plan_b = oy, oy + vbH * scale
    out += _dim_h(plan_l, plan_r, plan_b + max(wall, 8) + 22, vbW)
    out += _dim_v(plan_t, plan_b, plan_l - max(wall, 8) - 22, vbH)
    out += _scale_bar(M_L, H - 30, scale)
    out += _north_arrow(W - M_R - 14, H - 56)

    out.append("</svg>")
    return "\n".join(out)


def _door_swing(mp, x_world: float, z_world: float, orient: str,
                width_world: float, scale: float, wall: float) -> list[str]:
    """A hinged door: a gap punched in the wall poché, the leaf shown open, and
    a dashed quarter-circle swing arc. Hinged at ``(x_world, z_world)``; orient
    ``h`` runs the leaf along +x (swings into the room, -z), ``v`` along +z."""
    hx, hy = mp(x_world, z_world)
    wpx = width_world * scale
    if orient == "h":
        return [
            f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{hx + wpx:.1f}" y2="{hy:.1f}" stroke="{_FLOOR}" stroke-width="{wall + 2:.1f}"/>',
            f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{hx:.1f}" y2="{hy - wpx:.1f}" stroke="{_INK}" stroke-width="1.6"/>',
            f'<path d="M {hx:.1f} {hy - wpx:.1f} A {wpx:.1f} {wpx:.1f} 0 0 1 {hx + wpx:.1f} {hy:.1f}" fill="none" stroke="{_INK}" stroke-width="1" stroke-dasharray="3 3" opacity="0.6"/>',
        ]
    return [
        f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{hx:.1f}" y2="{hy + wpx:.1f}" stroke="{_FLOOR}" stroke-width="{wall + 2:.1f}"/>',
        f'<line x1="{hx:.1f}" y1="{hy:.1f}" x2="{hx + wpx:.1f}" y2="{hy:.1f}" stroke="{_INK}" stroke-width="1.6"/>',
        f'<path d="M {hx + wpx:.1f} {hy:.1f} A {wpx:.1f} {wpx:.1f} 0 0 1 {hx:.1f} {hy + wpx:.1f}" fill="none" stroke="{_INK}" stroke-width="1" stroke-dasharray="3 3" opacity="0.6"/>',
    ]


def _dim_h(x0: float, x1: float, y: float, meters: float) -> list[str]:
    """Horizontal dimension string with witness ticks and a centred label."""
    mid = (x0 + x1) / 2
    lbl = f"{meters:.2f} m"
    bw = len(lbl) * 6.6 + 8
    return [
        f'<line x1="{x0:.1f}" y1="{y - 5:.1f}" x2="{x0:.1f}" y2="{y + 5:.1f}" stroke="{_DIM}" stroke-width="1"/>',
        f'<line x1="{x1:.1f}" y1="{y - 5:.1f}" x2="{x1:.1f}" y2="{y + 5:.1f}" stroke="{_DIM}" stroke-width="1"/>',
        f'<line x1="{x0:.1f}" y1="{y:.1f}" x2="{x1:.1f}" y2="{y:.1f}" stroke="{_DIM}" stroke-width="1"/>',
        f'<rect x="{mid - bw / 2:.1f}" y="{y - 8:.1f}" width="{bw:.1f}" height="16" fill="{_PAPER}"/>',
        f'<text x="{mid:.1f}" y="{y + 4:.1f}" text-anchor="middle" fill="#6f6152" font-size="12">{lbl}</text>',
    ]


def _dim_v(y0: float, y1: float, x: float, meters: float) -> list[str]:
    """Vertical dimension string with witness ticks and a rotated label."""
    mid = (y0 + y1) / 2
    lbl = f"{meters:.2f} m"
    bh = len(lbl) * 6.6 + 8
    return [
        f'<line x1="{x - 5:.1f}" y1="{y0:.1f}" x2="{x + 5:.1f}" y2="{y0:.1f}" stroke="{_DIM}" stroke-width="1"/>',
        f'<line x1="{x - 5:.1f}" y1="{y1:.1f}" x2="{x + 5:.1f}" y2="{y1:.1f}" stroke="{_DIM}" stroke-width="1"/>',
        f'<line x1="{x:.1f}" y1="{y0:.1f}" x2="{x:.1f}" y2="{y1:.1f}" stroke="{_DIM}" stroke-width="1"/>',
        f'<rect x="{x - 8:.1f}" y="{mid - bh / 2:.1f}" width="16" height="{bh:.1f}" fill="{_PAPER}"/>',
        f'<text x="{x:.1f}" y="{mid:.1f}" text-anchor="middle" fill="#6f6152" font-size="12" transform="rotate(-90 {x:.1f} {mid:.1f})">{lbl}</text>',
    ]


def _scale_bar(x: float, y: float, scale: float) -> list[str]:
    """Two-segment scale bar sized to a 'nice' round distance for this scale."""
    seg_m = 1.0
    for u in (0.5, 1.0, 2.0, 5.0, 10.0):
        if u * scale <= 72:
            seg_m = u
    px = seg_m * scale
    return [
        f'<text x="{x:.1f}" y="{y - 7:.1f}" fill="#8a7a68" font-size="9.5" letter-spacing="0.08em">SCALE</text>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{px:.1f}" height="5" fill="{_INK}"/>',
        f'<rect x="{x + px:.1f}" y="{y:.1f}" width="{px:.1f}" height="5" fill="none" stroke="{_INK}" stroke-width="0.9"/>',
        f'<text x="{x:.1f}" y="{y + 16:.1f}" text-anchor="middle" fill="#8a7a68" font-size="9">0</text>',
        f'<text x="{x + 2 * px:.1f}" y="{y + 16:.1f}" text-anchor="middle" fill="#8a7a68" font-size="9">{2 * seg_m:g} m</text>',
    ]


def _north_arrow(x: float, y: float) -> list[str]:
    """A compact filled north arrow with an 'N' label."""
    return [
        f'<polygon points="{x:.1f},{y:.1f} {x - 6:.1f},{y + 17:.1f} {x:.1f},{y + 11:.1f} {x + 6:.1f},{y + 17:.1f}" fill="{_INK}"/>',
        f'<text x="{x:.1f}" y="{y + 31:.1f}" text-anchor="middle" fill="#6f6152" font-size="11" font-weight="700">N</text>',
    ]


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
