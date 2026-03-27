"""CAD-ready structured drawing engine for architectural and MEP outputs."""

from __future__ import annotations

import logging
from copy import deepcopy
from math import ceil, hypot

logger = logging.getLogger(__name__)

DEFAULT_SCALE_LABEL = "1:50"
DEFAULT_WALL_THICKNESS_M = 0.2
DEFAULT_DOOR_WIDTH_M = 0.9
DEFAULT_DOOR_HEIGHT_M = 2.1
DEFAULT_WINDOW_WIDTH_M = 1.5
DEFAULT_WINDOW_HEIGHT_M = 1.2
DEFAULT_WINDOW_SILL_M = 0.9
DEFAULT_SWITCH_HEIGHT_M = 1.2
DEFAULT_SOCKET_HEIGHT_M = 0.3
DEFAULT_LIGHT_OFFSET_FROM_CEILING_M = 0.3
DEFAULT_HVAC_COVERAGE_SQM = 16.0
CANVAS_EPSILON = 0.01
MEP_CONFLICT_DISTANCE_M = 0.3

LINE_SOLID = "solid"
LINE_DASHED = "dashed"
LINE_HIDDEN = "hidden"

SYMBOL_SWITCH = "switch"
SYMBOL_SOCKET = "socket"
SYMBOL_LIGHT = "light"
SYMBOL_VENT = "vent"
SYMBOL_FIXTURE = "fixture"

ESSENTIAL_FURNITURE_BY_ROOM = {
    "living_room": ["sofa", "coffee_table", "tv_unit"],
    "bedroom": ["bed", "wardrobe", "side_table"],
    "office": ["desk", "chair", "console"],
    "dining_room": ["dining_table", "chairs", "console"],
    "kitchen": ["base_cabinet", "sink", "counter"],
    "bathroom": ["toilet", "wash_basin", "shower"],
}

FURNITURE_HEIGHT_DEFAULTS = {
    "sofa": 0.85,
    "coffee_table": 0.45,
    "tv_unit": 0.65,
    "bed": 0.6,
    "wardrobe": 2.1,
    "side_table": 0.55,
    "desk": 0.76,
    "chair": 0.9,
    "chairs": 0.9,
    "dining_table": 0.76,
    "console": 0.9,
    "sink": 0.9,
    "wash_basin": 0.85,
    "toilet": 0.8,
    "shower": 2.1,
    "base_cabinet": 0.9,
    "counter": 0.9,
}

SOCKET_ELIGIBLE_TYPES = {
    "sofa",
    "tv_unit",
    "desk",
    "bed",
    "wardrobe",
    "console",
    "dining_table",
    "chair",
    "base_cabinet",
    "counter",
}

PLUMBING_FIXTURE_TYPES = {
    "sink",
    "wash_basin",
    "toilet",
    "shower",
    "bathtub",
    "dishwasher",
    "washing_machine",
}

EXAMPLE_INPUT = {
    "input_data": {
        "room_type": "living_room",
        "dimensions": {"length": 16, "width": 12, "height": 10, "unit": "ft"},
    },
    "theme_config": {
        "style": "modern",
        "materials": ["oak wood", "matte paint", "brushed metal"],
        "lighting": "layered warm ambient lighting",
    },
    "concept_data": {
        "design_intent": "Create a balanced family lounge with a clear entertainment focal wall.",
        "material_strategy": "Use warm timber accents with durable low-maintenance finishes.",
        "lighting_strategy": "Layer ambient, accent, and task lighting for evening comfort.",
    },
    "layout_data": {
        "furniture": [
            {
                "type": "sofa",
                "zone": "seating_area",
                "orientation": "facing north wall",
                "coordinates": {"x": 8, "y": 8, "z": 0},
                "size": {"width": 7, "depth": 3},
                "rotation": 0,
                "clearance": {"front": 3, "back": 0.5, "left": 1.5, "right": 1.5},
            },
            {
                "type": "coffee_table",
                "zone": "seating_area",
                "orientation": "centered on seating axis",
                "coordinates": {"x": 8, "y": 5.5, "z": 0},
                "size": {"width": 4, "depth": 2},
                "rotation": 0,
                "clearance": {"front": 1.5, "back": 1.5, "left": 1, "right": 1},
            },
            {
                "type": "tv_unit",
                "zone": "seating_area",
                "orientation": "facing seating",
                "coordinates": {"x": 8, "y": 1.5, "z": 0},
                "size": {"width": 5, "depth": 1.5},
                "rotation": 180,
                "clearance": {"front": 5, "back": 0.25, "left": 1, "right": 1},
            },
        ],
        "zones": [
            {"name": "seating_area", "purpose": "social interaction", "position": "center"},
            {"name": "circulation_zone", "purpose": "clear movement path", "position": "perimeter"},
        ],
        "relationships": [
            {"from": "sofa", "to": "tv_unit", "type": "facing"},
            {"from": "coffee_table", "to": "sofa", "type": "adjacent"},
        ],
        "grid": {"unit": 1.0, "snap": True},
        "spacing": {"walkways": "minimum 3 ft clearance", "furniture_gaps": "1-2 ft between elements"},
    },
}


def process(
    input_data: dict,
    theme_config: dict | None = None,
    concept_data: dict | None = None,
    layout_data: dict | None = None,
) -> dict:
    """Generate CAD-ready structured drawing data."""
    if layout_data is None:
        layout_data = deepcopy(input_data or {})
        input_data = {
            "room_type": layout_data.get("room_type", "space"),
            "dimensions": layout_data.get("dimensions", {}),
        }
        theme_config = theme_config or layout_data.get("theme_reference", {})
        concept_data = concept_data or {
            "design_intent": layout_data.get("layout_summary", ""),
            "material_strategy": "",
            "lighting_strategy": "",
        }

    input_data = deepcopy(input_data or {})
    theme_config = deepcopy(theme_config or {})
    concept_data = deepcopy(concept_data or {})
    layout_data = deepcopy(layout_data or {})

    logger.info(
        "drawing_generation_started",
        extra={"room_type": input_data.get("room_type"), "style": theme_config.get("style")},
    )

    try:
        normalized = validate_input_payloads(
            input_data=input_data,
            theme_config=theme_config,
            concept_data=concept_data,
            layout_data=layout_data,
        )
        geometry = GeometryBuilder(
            input_data=normalized["input_data"],
            theme_config=normalized["theme_config"],
            concept_data=normalized["concept_data"],
            layout_data=normalized["layout_data"],
        ).build()
        logger.info(
            "drawing_geometry_built",
            extra={"room_type": geometry["room_type"], "walls": len(geometry["walls"]), "furniture": len(geometry["furniture"])},
        )

        electrical = ElectricalPlanner(geometry, normalized["theme_config"], normalized["concept_data"]).build()
        plumbing = PlumbingPlanner(geometry, normalized["theme_config"], normalized["concept_data"]).build()
        hvac = HVACPlanner(geometry, normalized["theme_config"], normalized["concept_data"]).build()
        logger.info(
            "mep_planned",
            extra={"lights": len(electrical["lights"]), "pipes": len(plumbing["pipes"]), "vents": len(hvac["vents"])},
        )

        annotations = AnnotationBuilder(geometry).build(electrical=electrical, plumbing=plumbing, hvac=hvac)
        conflicts = ConflictDetector(geometry).detect(electrical=electrical, plumbing=plumbing, hvac=hvac)
        if conflicts:
            logger.warning("conflicts_detected", extra={"count": len(conflicts), "conflicts": conflicts})

        drawing = {
            "canvas": geometry["canvas"],
            "scale": geometry["scale"],
            "floor_plan": {
                "walls": geometry["walls"],
                "doors": geometry["doors"],
                "windows": geometry["windows"],
                "furniture": geometry["furniture"],
                "dimensions": annotations["dimensions"],
            },
            "elevation": {"views": build_elevations(geometry)},
            "section": {"cut_views": build_sections(geometry)},
            "electrical": electrical,
            "plumbing": plumbing,
            "hvac": hvac,
            "layers": annotations["layers"],
            "dimensions": annotations["dimensions"],
            "conflicts": conflicts,
        }
        validate_output_structure(drawing)
        logger.info(
            "drawing_generated",
            extra={"room_type": geometry["room_type"], "walls": len(geometry["walls"]), "furniture": len(geometry["furniture"]), "conflicts": len(conflicts)},
        )
        return drawing
    except Exception as exc:
        logger.exception("drawing_failed", extra={"room_type": input_data.get("room_type"), "error": str(exc)})
        raise


def validate_input_payloads(
    *,
    input_data: dict,
    theme_config: dict,
    concept_data: dict,
    layout_data: dict,
) -> dict:
    room_type = str(input_data.get("room_type") or layout_data.get("room_type") or "space").strip().lower()
    dimensions = _normalize_dimensions(input_data.get("dimensions") or layout_data.get("dimensions") or {})
    if dimensions["length"] <= 0 or dimensions["width"] <= 0 or dimensions["height"] <= 0:
        raise ValueError("Room dimensions must be positive")

    normalized_layout = deepcopy(layout_data)
    normalized_layout["room_type"] = room_type
    normalized_layout["dimensions"] = dimensions
    normalized_layout["canvas"] = _build_canvas(dimensions)
    normalized_layout["zones"] = _normalize_zones(layout_data.get("zones"))
    normalized_layout["relationships"] = _normalize_relationships(layout_data.get("relationships"))
    normalized_layout["grid"] = _normalize_grid(layout_data.get("grid"), dimensions)
    normalized_layout["spacing"] = _normalize_spacing(layout_data.get("spacing"))
    normalized_layout["furniture"] = _normalize_furniture(layout_data.get("furniture"), dimensions, room_type)

    normalized_theme = {
        "style": str(theme_config.get("style", "modern")).strip().lower(),
        "materials": list(theme_config.get("materials") or []),
        "lighting": str(theme_config.get("lighting", "")).strip(),
    }
    normalized_concept = {
        "design_intent": str(concept_data.get("design_intent", "")).strip(),
        "material_strategy": str(concept_data.get("material_strategy", "")).strip(),
        "lighting_strategy": str(concept_data.get("lighting_strategy", "")).strip(),
    }
    return {
        "input_data": {"room_type": room_type, "dimensions": dimensions},
        "theme_config": normalized_theme,
        "concept_data": normalized_concept,
        "layout_data": normalized_layout,
    }


def validate_output_structure(drawing: dict) -> None:
    required_top_level = {"canvas", "scale", "floor_plan", "elevation", "section", "electrical", "plumbing", "hvac", "layers", "dimensions", "conflicts"}
    missing = required_top_level.difference(drawing)
    if missing:
        raise ValueError(f"Drawing output missing sections: {sorted(missing)}")

    if drawing["canvas"].get("unit") not in {"ft", "m"}:
        raise ValueError("canvas.unit must be 'ft' or 'm'")
    if drawing["canvas"].get("scale") != 1:
        raise ValueError("canvas.scale must be 1")

    for key in ("walls", "doors", "windows", "furniture", "dimensions"):
        if not isinstance(drawing["floor_plan"].get(key), list):
            raise ValueError(f"floor_plan.{key} must be a list")
    if not isinstance(drawing["elevation"].get("views"), list):
        raise ValueError("elevation.views must be a list")
    if not isinstance(drawing["section"].get("cut_views"), list):
        raise ValueError("section.cut_views must be a list")
    for key in ("walls", "furniture", "electrical", "plumbing", "hvac"):
        if not isinstance(drawing["layers"].get(key), list):
            raise ValueError(f"layers.{key} must be a list")
    for system_name, keys in {"electrical": ("lights", "switches", "sockets"), "plumbing": ("pipes", "fixtures"), "hvac": ("vents", "units")}.items():
        payload = drawing[system_name]
        for key in keys:
            if not isinstance(payload.get(key), list):
                raise ValueError(f"{system_name}.{key} must be a list")

    _validate_canvas_alignment(drawing)
    _validate_mep_placements(drawing)


def generate_example_output() -> dict:
    return process(
        EXAMPLE_INPUT["input_data"],
        EXAMPLE_INPUT["theme_config"],
        EXAMPLE_INPUT["concept_data"],
        EXAMPLE_INPUT["layout_data"],
    )


class GeometryBuilder:
    """Build core geometry and CAD metadata."""

    def __init__(self, *, input_data: dict, theme_config: dict, concept_data: dict, layout_data: dict) -> None:
        self.input_data = input_data
        self.theme_config = theme_config
        self.concept_data = concept_data
        self.layout_data = layout_data
        self.dimensions = input_data["dimensions"]
        self.canvas = _build_canvas(self.dimensions)

    def build(self) -> dict:
        furniture = self.build_furniture()
        return {
            "room_type": self.input_data["room_type"],
            "dimensions": self.dimensions,
            "canvas": self.canvas,
            "scale": DEFAULT_SCALE_LABEL,
            "theme_config": self.theme_config,
            "concept_data": self.concept_data,
            "layout_data": self.layout_data,
            "walls": self.build_walls(),
            "doors": self.build_doors(self.select_entry_wall(furniture)),
            "windows": self.build_windows(),
            "furniture": furniture,
            "zones": self.layout_data.get("zones", []),
            "relationships": self.layout_data.get("relationships", []),
            "grid": self.layout_data.get("grid", {}),
            "spacing": self.layout_data.get("spacing", {}),
        }

    def build_walls(self) -> list[dict]:
        length = self.dimensions["length"]
        width = self.dimensions["width"]
        height = self.dimensions["height"]
        thickness = _wall_thickness_for_unit(self.dimensions["unit"])
        return [
            _wall_record("wall_north", "north", (0, 0, 0), (length, 0, 0), thickness, height),
            _wall_record("wall_east", "east", (length, 0, 0), (length, width, 0), thickness, height),
            _wall_record("wall_south", "south", (length, width, 0), (0, width, 0), thickness, height),
            _wall_record("wall_west", "west", (0, width, 0), (0, 0, 0), thickness, height),
        ]

    def build_furniture(self) -> list[dict]:
        items = []
        for index, item in enumerate(self.layout_data.get("furniture", []), start=1):
            coordinates = item["coordinates"]
            size = item["size"]
            width = float(size["width"])
            depth = float(size["depth"])
            height = float(size.get("height") or FURNITURE_HEIGHT_DEFAULTS.get(item["type"], 0.9))
            items.append(
                {
                    "id": item.get("id", f"furniture_{index}"),
                    "type": item["type"],
                    "zone": item.get("zone", "primary_area"),
                    "position": {"x": coordinates["x"], "y": coordinates["y"], "z": coordinates.get("z", 0.0)},
                    "size": {"width": width, "depth": depth, "height": height},
                    "rotation": item.get("rotation", 0),
                    "orientation": item.get("orientation", ""),
                    "clearance": item.get("clearance") or _default_clearance(),
                    "bbox": _bbox_from_center(coordinates["x"], coordinates["y"], width, depth, height),
                    "line_type": LINE_SOLID,
                    "render_hint": {"symbol": item["type"], "convertible_to": ["svg", "cad", "3d"]},
                }
            )
        return items

    def select_entry_wall(self, furniture: list[dict]) -> str:
        if self.input_data["room_type"] in {"bathroom", "toilet", "powder_room"}:
            return "south"
        if any(item["type"] in {"tv_unit", "console"} and item["position"]["y"] <= self.dimensions["width"] * 0.25 for item in furniture):
            return "west"
        return "south"

    def build_doors(self, entry_wall: str) -> list[dict]:
        door_width = _scaled_value(DEFAULT_DOOR_WIDTH_M, self.dimensions["unit"])
        center = self._find_open_span(entry_wall, door_width)
        line = _opening_line(entry_wall, center, door_width, self.dimensions)
        return [
            {
                "id": "door_main",
                "type": "swing",
                "wall": entry_wall,
                "position": {"x": line["center"][0], "y": line["center"][1], "z": 0.0},
                "size": {"width": door_width, "height": _scaled_value(DEFAULT_DOOR_HEIGHT_M, self.dimensions["unit"])},
                "swing_direction": "inward_left",
                "line": line["segment"],
                "line_type": LINE_SOLID,
                "render_hint": {"convertible_to": ["svg", "cad"]},
            }
        ]

    def build_windows(self) -> list[dict]:
        preferred_walls = ["east", "north"]
        if "natural" not in self.theme_config.get("lighting", "").lower() and "natural" not in self.concept_data.get("lighting_strategy", "").lower():
            preferred_walls = ["north", "east"]

        windows = []
        for index, wall in enumerate(preferred_walls, start=1):
            width = _scaled_value(DEFAULT_WINDOW_WIDTH_M, self.dimensions["unit"])
            center = self._find_open_span(wall, width)
            line = _opening_line(wall, center, width, self.dimensions)
            windows.append(
                {
                    "id": f"window_{index}",
                    "type": "sliding",
                    "wall": wall,
                    "position": {"x": line["center"][0], "y": line["center"][1], "z": _scaled_value(DEFAULT_WINDOW_SILL_M, self.dimensions["unit"])},
                    "size": {"width": width, "height": _scaled_value(DEFAULT_WINDOW_HEIGHT_M, self.dimensions["unit"])},
                    "head_height": round(_scaled_value(DEFAULT_WINDOW_SILL_M + DEFAULT_WINDOW_HEIGHT_M, self.dimensions["unit"]), 2),
                    "line": line["segment"],
                    "line_type": LINE_SOLID,
                    "render_hint": {"convertible_to": ["svg", "cad"]},
                }
            )
        return windows

    def _find_open_span(self, wall: str, opening_width: float) -> float:
        span_length = self.dimensions["length"] if wall in {"north", "south"} else self.dimensions["width"]
        for ratio in (0.25, 0.5, 0.75):
            center = span_length * ratio
            if self._wall_span_is_clear(wall, center, opening_width):
                return round(center, 2)
        return round(span_length / 2, 2)

    def _wall_span_is_clear(self, wall: str, center: float, opening_width: float) -> bool:
        span_min = center - opening_width / 2
        span_max = center + opening_width / 2
        threshold = _scaled_value(0.6, self.dimensions["unit"])
        for item in self.layout_data.get("furniture", []):
            coordinates = item["coordinates"]
            size = item["size"]
            min_x = coordinates["x"] - size["width"] / 2
            max_x = coordinates["x"] + size["width"] / 2
            min_y = coordinates["y"] - size["depth"] / 2
            max_y = coordinates["y"] + size["depth"] / 2
            if wall == "north" and min_y <= threshold and _ranges_overlap(span_min, span_max, min_x, max_x):
                return False
            if wall == "south" and max_y >= self.dimensions["width"] - threshold and _ranges_overlap(span_min, span_max, min_x, max_x):
                return False
            if wall == "west" and min_x <= threshold and _ranges_overlap(span_min, span_max, min_y, max_y):
                return False
            if wall == "east" and max_x >= self.dimensions["length"] - threshold and _ranges_overlap(span_min, span_max, min_y, max_y):
                return False
        return True


class ElectricalPlanner:
    """Plan lighting, switches, and sockets."""

    def __init__(self, geometry: dict, theme_config: dict, concept_data: dict) -> None:
        self.geometry = geometry
        self.theme_config = theme_config
        self.concept_data = concept_data
        self.dimensions = geometry["dimensions"]

    def build(self) -> dict:
        lights = self.build_lights()
        return {"lights": lights, "switches": self.build_switches(lights), "sockets": self.build_sockets()}

    def build_lights(self) -> list[dict]:
        z = max(self.dimensions["height"] - _scaled_value(DEFAULT_LIGHT_OFFSET_FROM_CEILING_M, self.dimensions["unit"]), 0.1)
        centers = _zone_centers(self.geometry["zones"], self.geometry["furniture"], self.dimensions)
        return [
            {
                "id": f"light_{index}",
                "type": "ceiling",
                "symbol": SYMBOL_LIGHT,
                "zone": center["zone"],
                "position": {"x": center["x"], "y": center["y"], "z": round(z, 2)},
                "fixture": _lighting_fixture_for_zone(center["zone"], self.theme_config),
                "circuit": f"L{index}",
                "line_type": LINE_SOLID,
                "render_hint": {"convertible_to": ["svg", "cad", "3d"]},
            }
            for index, center in enumerate(centers, start=1)
        ]

    def build_switches(self, lights: list[dict]) -> list[dict]:
        switches = []
        for index, door in enumerate(self.geometry["doors"], start=1):
            point = _point_near_entry(door["wall"], self.dimensions, offset_primary=0.45, offset_secondary=0.25)
            switches.append(
                {
                    "id": f"switch_{index}",
                    "type": "gang_1",
                    "symbol": SYMBOL_SWITCH,
                    "near_door": door["id"],
                    "position": {"x": point["x"], "y": point["y"], "z": round(_scaled_value(DEFAULT_SWITCH_HEIGHT_M, self.dimensions["unit"]), 2)},
                    "controls": [light["id"] for light in lights],
                    "line_type": LINE_SOLID,
                    "render_hint": {"convertible_to": ["svg", "cad"]},
                }
            )
        return switches

    def build_sockets(self) -> list[dict]:
        sockets = []
        for index, furniture in enumerate(self.geometry["furniture"], start=1):
            if furniture["type"] not in SOCKET_ELIGIBLE_TYPES:
                continue
            wall = _nearest_wall(furniture["position"], self.dimensions)
            point = _point_near_furniture_wall(furniture, wall, self.dimensions)
            sockets.append(
                {
                    "id": f"socket_{index}",
                    "type": "duplex",
                    "symbol": SYMBOL_SOCKET,
                    "near_furniture": furniture["id"],
                    "wall": wall,
                    "position": {"x": point["x"], "y": point["y"], "z": round(_scaled_value(DEFAULT_SOCKET_HEIGHT_M, self.dimensions["unit"]), 2)},
                    "load_hint": _socket_load_hint(furniture["type"]),
                    "line_type": LINE_SOLID,
                    "render_hint": {"convertible_to": ["svg", "cad"]},
                }
            )
        return sockets


class PlumbingPlanner:
    """Generate fixtures and routing for wet rooms."""

    def __init__(self, geometry: dict, theme_config: dict, concept_data: dict) -> None:
        self.geometry = geometry
        self.theme_config = theme_config
        self.concept_data = concept_data
        self.dimensions = geometry["dimensions"]

    def build(self) -> dict:
        fixtures = self.build_fixtures()
        return {"pipes": self.build_pipes(fixtures), "fixtures": fixtures}

    def build_fixtures(self) -> list[dict]:
        room_type = self.geometry["room_type"]
        if room_type not in {"kitchen", "bathroom", "toilet", "powder_room", "laundry"} and not any(item["type"] in PLUMBING_FIXTURE_TYPES for item in self.geometry["furniture"]):
            return []

        fixtures = []
        for item in self.geometry["furniture"]:
            if item["type"] not in PLUMBING_FIXTURE_TYPES:
                continue
            wall = _nearest_wall(item["position"], self.dimensions)
            fixtures.append(
                {
                    "id": f"fixture_{item['id']}",
                    "type": item["type"],
                    "symbol": SYMBOL_FIXTURE,
                    "wall": wall,
                    "position": item["position"],
                    "service_point": _plumbing_service_point(item["position"], wall, self.dimensions),
                    "line_type": LINE_DASHED,
                    "render_hint": {"convertible_to": ["svg", "cad", "3d"]},
                }
            )
        if fixtures:
            return fixtures

        default_type = "sink" if room_type == "kitchen" else "wash_basin"
        position = {"x": round(self.dimensions["length"] * 0.18, 2), "y": round(self.dimensions["width"] * 0.2, 2), "z": 0.0}
        return [
            {
                "id": "fixture_primary",
                "type": default_type,
                "symbol": SYMBOL_FIXTURE,
                "wall": "north",
                "position": position,
                "service_point": _plumbing_service_point(position, "north", self.dimensions),
                "line_type": LINE_DASHED,
                "render_hint": {"convertible_to": ["svg", "cad", "3d"]},
            }
        ]

    def build_pipes(self, fixtures: list[dict]) -> list[dict]:
        pipes = []
        for index, fixture in enumerate(fixtures, start=1):
            service = fixture["service_point"]
            pipes.append(
                {
                    "id": f"pipe_supply_{index}",
                    "type": "water_supply",
                    "fixture_id": fixture["id"],
                    "path": [
                        {"x": service["x"], "y": service["y"], "z": 0.0},
                        {"x": service["x"], "y": service["y"], "z": round(_scaled_value(0.6, self.dimensions["unit"]), 2)},
                    ],
                    "diameter": _scaled_value(0.02, self.dimensions["unit"]),
                    "line_type": LINE_DASHED,
                    "render_hint": {"convertible_to": ["svg", "cad", "3d"]},
                }
            )
            pipes.append(
                {
                    "id": f"pipe_waste_{index}",
                    "type": "waste",
                    "fixture_id": fixture["id"],
                    "path": [
                        {"x": service["x"], "y": service["y"], "z": 0.0},
                        {"x": round(self.dimensions["length"] * 0.05, 2), "y": round(self.dimensions["width"] * 0.05, 2), "z": 0.0},
                    ],
                    "diameter": _scaled_value(0.05, self.dimensions["unit"]),
                    "line_type": LINE_DASHED,
                    "render_hint": {"convertible_to": ["svg", "cad", "3d"]},
                }
            )
        return pipes


class HVACPlanner:
    """Generate vents and units for airflow coverage."""

    def __init__(self, geometry: dict, theme_config: dict, concept_data: dict) -> None:
        self.geometry = geometry
        self.theme_config = theme_config
        self.concept_data = concept_data
        self.dimensions = geometry["dimensions"]

    def build(self) -> dict:
        units = self.build_units()
        return {"vents": self.build_vents(units), "units": units}

    def build_units(self) -> list[dict]:
        return [
            {
                "id": "hvac_unit_1",
                "type": "split_ac_indoor",
                "wall": "east",
                "position": {
                    "x": round(self.dimensions["length"] - _scaled_value(0.25, self.dimensions["unit"]), 2),
                    "y": round(self.dimensions["width"] / 2, 2),
                    "z": round(self.dimensions["height"] * 0.75, 2),
                },
                "coverage_radius": round(_scaled_area_value(DEFAULT_HVAC_COVERAGE_SQM, self.dimensions["unit"]), 2),
                "line_type": LINE_SOLID,
                "render_hint": {"convertible_to": ["svg", "cad", "3d"]},
            }
        ]

    def build_vents(self, units: list[dict]) -> list[dict]:
        coverage = _scaled_area_value(DEFAULT_HVAC_COVERAGE_SQM, self.dimensions["unit"])
        vent_count = min(4, max(1, ceil((self.dimensions["length"] * self.dimensions["width"]) / coverage)))
        z = round(self.dimensions["height"] - _scaled_value(0.2, self.dimensions["unit"]), 2)
        vents = []
        for index in range(vent_count):
            vents.append(
                {
                    "id": f"vent_{index + 1}",
                    "type": "supply_vent",
                    "symbol": SYMBOL_VENT,
                    "position": {
                        "x": round(self.dimensions["length"] * ((index + 1) / (vent_count + 1)), 2),
                        "y": round(self.dimensions["width"] / 2 if index % 2 == 0 else self.dimensions["width"] * 0.35, 2),
                        "z": z,
                    },
                    "served_by": units[0]["id"] if units else None,
                    "airflow_direction": "toward_room_center",
                    "line_type": LINE_SOLID,
                    "render_hint": {"convertible_to": ["svg", "cad", "3d"]},
                }
            )
        return vents


class AnnotationBuilder:
    """Generate layer maps and dimension annotations."""

    def __init__(self, geometry: dict) -> None:
        self.geometry = geometry
        self.dimensions = geometry["dimensions"]

    def build(self, *, electrical: dict, plumbing: dict, hvac: dict) -> dict:
        return {
            "layers": {
                "walls": self.geometry["walls"] + self.geometry["doors"] + self.geometry["windows"],
                "furniture": self.geometry["furniture"] + self._hidden_edges(),
                "electrical": electrical["lights"] + electrical["switches"] + electrical["sockets"],
                "plumbing": plumbing["pipes"] + plumbing["fixtures"],
                "hvac": hvac["vents"] + hvac["units"],
            },
            "dimensions": self.build_dimensions(),
        }

    def build_dimensions(self) -> list[dict]:
        return [
            {
                "from": [0.0, 0.0],
                "to": [round(self.dimensions["length"], 2), 0.0],
                "label": _format_dimension(self.dimensions["length"], self.dimensions["unit"]),
            },
            {
                "from": [0.0, 0.0],
                "to": [0.0, round(self.dimensions["width"], 2)],
                "label": _format_dimension(self.dimensions["width"], self.dimensions["unit"]),
            },
        ]

    def _hidden_edges(self) -> list[dict]:
        return [
            {
                "id": f"hidden_{item['id']}",
                "type": "hidden_edge",
                "target": item["id"],
                "bbox": item["bbox"],
                "line_type": LINE_HIDDEN,
            }
            for item in self.geometry["furniture"]
        ]


class ConflictDetector:
    """Detect simple inter-discipline conflicts."""

    def __init__(self, geometry: dict) -> None:
        self.geometry = geometry
        self.unit = geometry["dimensions"]["unit"]

    def detect(self, *, electrical: dict, plumbing: dict, hvac: dict) -> list[str]:
        conflicts: list[str] = []
        for electrical_point in electrical["switches"] + electrical["sockets"]:
            for fixture in plumbing["fixtures"]:
                if _distance_3d(electrical_point["position"], fixture["position"]) <= _scaled_value(MEP_CONFLICT_DISTANCE_M, self.unit):
                    conflicts.append("electrical overlaps plumbing")
                    break
        for vent in hvac["vents"]:
            if _point_near_beam_zone(vent["position"], self.geometry["dimensions"]):
                conflicts.append("hvac intersects beam")
                break
        return list(dict.fromkeys(conflicts))


def build_elevations(geometry: dict) -> list[dict]:
    views = []
    for name, wall in (("front", "north"), ("side", "east")):
        views.append(
            {
                "id": f"elevation_{name}",
                "name": name,
                "wall": wall,
                "wall_height": geometry["dimensions"]["height"],
                "scale": geometry["scale"],
                "openings": _elevation_openings_for_wall(geometry, wall),
                "furniture": _elevation_furniture_for_wall(geometry["furniture"], wall, geometry["dimensions"]),
            }
        )
    return views


def build_sections(geometry: dict) -> list[dict]:
    dimensions = geometry["dimensions"]
    sections = []
    for section_id, kind, cut_line in [
        ("section_a", "longitudinal", [{"x": round(dimensions["length"] / 2, 2), "y": 0.0}, {"x": round(dimensions["length"] / 2, 2), "y": dimensions["width"]}]),
        ("section_b", "cross", [{"x": 0.0, "y": round(dimensions["width"] / 2, 2)}, {"x": dimensions["length"], "y": round(dimensions["width"] / 2, 2)}]),
    ]:
        sections.append(
            {
                "id": section_id,
                "type": kind,
                "scale": geometry["scale"],
                "cut_line": cut_line,
                "floor_level": 0.0,
                "ceiling_level": dimensions["height"],
                "elements": _section_elements(geometry["furniture"], kind, dimensions),
            }
        )
    return sections


def _normalize_dimensions(dimensions: dict) -> dict:
    unit = str(dimensions.get("unit", "ft")).strip().lower()
    if unit not in {"ft", "m"}:
        unit = "ft"
    return {
        "length": round(float(dimensions.get("length", 12)), 2),
        "width": round(float(dimensions.get("width", 10)), 2),
        "height": round(float(dimensions.get("height", 10)), 2),
        "unit": unit,
    }


def _build_canvas(dimensions: dict) -> dict:
    return {"origin": {"x": 0, "y": 0}, "unit": dimensions["unit"], "scale": 1}


def _normalize_grid(grid: dict | None, dimensions: dict) -> dict:
    grid = grid or {}
    return {"unit": float(grid.get("unit", 1.0 if dimensions["unit"] == "ft" else 0.3)), "snap": bool(grid.get("snap", True))}


def _normalize_spacing(spacing: dict | None) -> dict:
    spacing = spacing or {}
    return {"walkways": str(spacing.get("walkways", "")), "furniture_gaps": str(spacing.get("furniture_gaps", ""))}


def _normalize_zones(zones: list | None) -> list[dict]:
    result = []
    for zone in zones or []:
        if isinstance(zone, dict):
            result.append(
                {
                    "name": str(zone.get("name", "")).strip() or "primary_area",
                    "purpose": str(zone.get("purpose", "")).strip(),
                    "position": str(zone.get("position", "")).strip(),
                }
            )
    return result


def _normalize_relationships(relationships: list | None) -> list[dict]:
    result = []
    for relationship in relationships or []:
        if not isinstance(relationship, dict):
            continue
        if relationship.get("from") and relationship.get("to") and relationship.get("type"):
            result.append(
                {
                    "from": str(relationship["from"]).strip(),
                    "to": str(relationship["to"]).strip(),
                    "type": str(relationship["type"]).strip(),
                }
            )
    return result


def _normalize_furniture(furniture: list | None, dimensions: dict, room_type: str) -> list[dict]:
    result = []
    for index, item in enumerate(furniture or [], start=1):
        if not isinstance(item, dict):
            continue
        position = item.get("coordinates") or {"x": item.get("position", {}).get("x"), "y": item.get("position", {}).get("z"), "z": item.get("position", {}).get("y", 0)}
        size = item.get("size") or {"width": item.get("dimensions", {}).get("length"), "depth": item.get("dimensions", {}).get("width"), "height": item.get("dimensions", {}).get("height")}
        if position.get("x") is None or position.get("y") is None or size.get("width") is None or size.get("depth") is None:
            continue
        result.append(
            {
                "id": item.get("id", f"{item.get('type', 'item')}_{index}"),
                "type": str(item.get("type", "generic")).strip().lower(),
                "zone": str(item.get("zone", "primary_area")).strip(),
                "orientation": str(item.get("orientation", "")).strip(),
                "rotation": int(round(float(item.get("rotation", 0)))),
                "coordinates": {
                    "x": _bound(float(position["x"]), 0.0, dimensions["length"]),
                    "y": _bound(float(position["y"]), 0.0, dimensions["width"]),
                    "z": float(position.get("z", 0.0) or 0.0),
                },
                "size": {
                    "width": round(max(float(size["width"]), 0.2), 2),
                    "depth": round(max(float(size["depth"]), 0.2), 2),
                    "height": round(max(float(size.get("height") or FURNITURE_HEIGHT_DEFAULTS.get(str(item.get("type", "")).strip().lower(), 0.9)), 0.2), 2),
                },
                "clearance": _normalize_clearance(item.get("clearance"), dimensions),
            }
        )
    return result or _build_fallback_furniture(room_type, dimensions)


def _build_fallback_furniture(room_type: str, dimensions: dict) -> list[dict]:
    types = ESSENTIAL_FURNITURE_BY_ROOM.get(room_type, ["sofa", "coffee_table"])
    center_x = dimensions["length"] / 2
    center_y = dimensions["width"] / 2
    spacing = _scaled_value(2.5, dimensions["unit"])
    items = []
    for index, furniture_type in enumerate(types, start=1):
        items.append(
            {
                "id": f"{furniture_type}_{index}",
                "type": furniture_type,
                "zone": "primary_area",
                "orientation": "fallback placement",
                "rotation": 0,
                "coordinates": {"x": round(center_x, 2), "y": round(max(1.0, center_y + (index - 2) * spacing), 2), "z": 0.0},
                "size": {
                    "width": 6.0 if furniture_type in {"sofa", "bed", "dining_table"} else 3.0,
                    "depth": 3.0 if furniture_type in {"sofa", "desk", "tv_unit"} else 2.0,
                    "height": FURNITURE_HEIGHT_DEFAULTS.get(furniture_type, 0.9),
                },
                "clearance": _default_clearance(),
            }
        )
    return items


def _normalize_clearance(clearance: dict | None, dimensions: dict) -> dict:
    clearance = clearance or _default_clearance()
    return {
        "front": round(float(clearance.get("front", 1.0)), 2),
        "back": round(float(clearance.get("back", 0.5)), 2),
        "left": round(float(clearance.get("left", 0.5)), 2),
        "right": round(float(clearance.get("right", 0.5)), 2),
        "unit": dimensions["unit"],
    }


def _default_clearance() -> dict:
    return {"front": 1.0, "back": 0.5, "left": 0.5, "right": 0.5}


def _wall_record(wall_id: str, side: str, start: tuple[float, float, float], end: tuple[float, float, float], thickness: float, height: float) -> dict:
    return {
        "id": wall_id,
        "side": side,
        "start": {"x": round(start[0], 2), "y": round(start[1], 2), "z": round(start[2], 2)},
        "end": {"x": round(end[0], 2), "y": round(end[1], 2), "z": round(end[2], 2)},
        "thickness": round(thickness, 2),
        "height": round(height, 2),
        "line_type": LINE_SOLID,
        "render_hint": {"convertible_to": ["svg", "cad", "3d"]},
    }


def _opening_line(wall: str, center: float, width: float, dimensions: dict) -> dict:
    half = width / 2
    if wall == "north":
        segment = [{"x": round(center - half, 2), "y": 0.0}, {"x": round(center + half, 2), "y": 0.0}]
        point = (center, 0.0)
    elif wall == "south":
        segment = [{"x": round(center - half, 2), "y": round(dimensions["width"], 2)}, {"x": round(center + half, 2), "y": round(dimensions["width"], 2)}]
        point = (center, dimensions["width"])
    elif wall == "west":
        segment = [{"x": 0.0, "y": round(center - half, 2)}, {"x": 0.0, "y": round(center + half, 2)}]
        point = (0.0, center)
    else:
        segment = [{"x": round(dimensions["length"], 2), "y": round(center - half, 2)}, {"x": round(dimensions["length"], 2), "y": round(center + half, 2)}]
        point = (dimensions["length"], center)
    return {"segment": segment, "center": point}


def _bbox_from_center(x: float, y: float, width: float, depth: float, height: float) -> dict:
    return {
        "min_x": round(x - width / 2, 2),
        "max_x": round(x + width / 2, 2),
        "min_y": round(y - depth / 2, 2),
        "max_y": round(y + depth / 2, 2),
        "min_z": 0.0,
        "max_z": round(height, 2),
    }


def _validate_canvas_alignment(drawing: dict) -> None:
    walls = drawing["floor_plan"]["walls"]
    max_x = max(point["x"] for wall in walls for point in (wall["start"], wall["end"]))
    max_y = max(point["y"] for wall in walls for point in (wall["start"], wall["end"]))
    for group in (
        drawing["floor_plan"]["walls"],
        drawing["floor_plan"]["doors"],
        drawing["floor_plan"]["windows"],
        drawing["floor_plan"]["furniture"],
        drawing["electrical"]["lights"],
        drawing["electrical"]["switches"],
        drawing["electrical"]["sockets"],
        drawing["plumbing"]["fixtures"],
        drawing["hvac"]["vents"],
        drawing["hvac"]["units"],
    ):
        for item in group:
            position = item.get("position")
            if position and not _point_within_canvas(position, max_x, max_y):
                raise ValueError(f"{item.get('id', 'element')} lies outside the canvas")


def _validate_mep_placements(drawing: dict) -> None:
    for switch in drawing["electrical"]["switches"]:
        if switch["position"]["z"] <= 0:
            raise ValueError(f"{switch['id']} has invalid switch height")
    for socket in drawing["electrical"]["sockets"]:
        if socket["position"]["z"] < 0:
            raise ValueError(f"{socket['id']} has invalid socket height")
    for pipe in drawing["plumbing"]["pipes"]:
        if len(pipe["path"]) < 2:
            raise ValueError(f"{pipe['id']} must contain at least two points")
    for vent in drawing["hvac"]["vents"]:
        if vent["position"]["z"] <= 0:
            raise ValueError(f"{vent['id']} has invalid vent height")


def _point_within_canvas(point: dict, length: float, width: float) -> bool:
    return -CANVAS_EPSILON <= point["x"] <= length + CANVAS_EPSILON and -CANVAS_EPSILON <= point["y"] <= width + CANVAS_EPSILON


def _ranges_overlap(start_a: float, end_a: float, start_b: float, end_b: float) -> bool:
    return max(start_a, start_b) <= min(end_a, end_b)


def _zone_centers(zones: list[dict], furniture: list[dict], dimensions: dict) -> list[dict]:
    centers = []
    for zone in zones:
        zone_furniture = [item for item in furniture if item["zone"] == zone["name"]]
        if zone_furniture:
            centers.append(
                {
                    "zone": zone["name"],
                    "x": round(sum(item["position"]["x"] for item in zone_furniture) / len(zone_furniture), 2),
                    "y": round(sum(item["position"]["y"] for item in zone_furniture) / len(zone_furniture), 2),
                }
            )
    return centers or [{"zone": "primary_area", "x": round(dimensions["length"] / 2, 2), "y": round(dimensions["width"] / 2, 2)}]


def _lighting_fixture_for_zone(zone_name: str, theme_config: dict) -> str:
    lighting = theme_config.get("lighting", "").lower()
    if "dramatic" in lighting:
        return "pendant"
    if zone_name in {"work_area", "desk_area"}:
        return "linear"
    return "recessed"


def _point_near_entry(wall: str, dimensions: dict, *, offset_primary: float, offset_secondary: float) -> dict:
    primary = _scaled_value(offset_primary, dimensions["unit"])
    secondary = _scaled_value(offset_secondary, dimensions["unit"])
    if wall == "south":
        return {"x": round(dimensions["length"] / 2 + primary, 2), "y": round(dimensions["width"] - secondary, 2)}
    if wall == "north":
        return {"x": round(dimensions["length"] / 2 + primary, 2), "y": round(secondary, 2)}
    if wall == "west":
        return {"x": round(secondary, 2), "y": round(dimensions["width"] / 2 + primary, 2)}
    return {"x": round(dimensions["length"] - secondary, 2), "y": round(dimensions["width"] / 2 + primary, 2)}


def _nearest_wall(position: dict, dimensions: dict) -> str:
    distances = {
        "north": position["y"],
        "south": dimensions["width"] - position["y"],
        "west": position["x"],
        "east": dimensions["length"] - position["x"],
    }
    return min(distances, key=distances.get)


def _point_near_furniture_wall(furniture: dict, wall: str, dimensions: dict) -> dict:
    inset = _scaled_value(0.15, dimensions["unit"])
    if wall == "north":
        return {"x": round(furniture["position"]["x"], 2), "y": round(inset, 2)}
    if wall == "south":
        return {"x": round(furniture["position"]["x"], 2), "y": round(dimensions["width"] - inset, 2)}
    if wall == "west":
        return {"x": round(inset, 2), "y": round(furniture["position"]["y"], 2)}
    return {"x": round(dimensions["length"] - inset, 2), "y": round(furniture["position"]["y"], 2)}


def _socket_load_hint(furniture_type: str) -> str:
    if furniture_type in {"tv_unit", "console"}:
        return "media"
    if furniture_type in {"desk", "chair"}:
        return "workstation"
    if furniture_type in {"bed", "sofa"}:
        return "convenience"
    return "general"


def _plumbing_service_point(position: dict, wall: str, dimensions: dict) -> dict:
    inset = _scaled_value(0.1, dimensions["unit"])
    if wall == "north":
        return {"x": round(position["x"], 2), "y": round(inset, 2)}
    if wall == "south":
        return {"x": round(position["x"], 2), "y": round(dimensions["width"] - inset, 2)}
    if wall == "west":
        return {"x": round(inset, 2), "y": round(position["y"], 2)}
    return {"x": round(dimensions["length"] - inset, 2), "y": round(position["y"], 2)}


def _elevation_openings_for_wall(geometry: dict, wall: str) -> list[dict]:
    result = []
    for opening in geometry["doors"] + geometry["windows"]:
        if opening["wall"] == wall:
            result.append(
                {
                    "id": opening["id"],
                    "type": opening["type"],
                    "base_level": round(opening["position"]["z"], 2),
                    "height": round(opening["size"]["height"], 2),
                    "width": round(opening["size"]["width"], 2),
                    "line_type": opening["line_type"],
                }
            )
    return result


def _elevation_furniture_for_wall(furniture: list[dict], wall: str, dimensions: dict) -> list[dict]:
    threshold = _scaled_value(2.5, dimensions["unit"])
    items = []
    for item in furniture:
        include = wall == "north" and item["position"]["y"] <= threshold
        projection = item["position"]["x"]
        if wall == "east" and item["position"]["x"] >= dimensions["length"] - threshold:
            include = True
            projection = item["position"]["y"]
        if include:
            items.append(
                {
                    "id": item["id"],
                    "type": item["type"],
                    "projection_offset": round(projection, 2),
                    "height": round(item["size"]["height"], 2),
                    "base_level": 0.0,
                    "line_type": item["line_type"],
                }
            )
    return items


def _section_elements(furniture: list[dict], kind: str, dimensions: dict) -> list[dict]:
    threshold = _scaled_value(1.5, dimensions["unit"])
    axis = dimensions["length"] / 2 if kind == "longitudinal" else dimensions["width"] / 2
    elements = []
    for item in furniture:
        coordinate = item["position"]["x"] if kind == "longitudinal" else item["position"]["y"]
        if abs(coordinate - axis) <= threshold:
            elements.append(
                {
                    "id": item["id"],
                    "type": item["type"],
                    "height": item["size"]["height"],
                    "base_level": 0.0,
                    "cut": True,
                    "line_type": item["line_type"],
                }
            )
    return elements


def _point_near_beam_zone(point: dict, dimensions: dict) -> bool:
    beam_y = dimensions["width"] * 0.5
    return abs(point["y"] - beam_y) <= _scaled_value(0.2, dimensions["unit"]) and point["z"] >= dimensions["height"] * 0.8


def _distance_3d(point_a: dict, point_b: dict) -> float:
    return hypot(hypot(point_a["x"] - point_b["x"], point_a["y"] - point_b["y"]), point_a.get("z", 0.0) - point_b.get("z", 0.0))


def _format_dimension(value: float, unit: str) -> str:
    return f"{round(value, 2)} {unit}"


def _wall_thickness_for_unit(unit: str) -> float:
    return round(DEFAULT_WALL_THICKNESS_M if unit == "m" else DEFAULT_WALL_THICKNESS_M * 3.28084, 2)


def _scaled_value(value_in_meters: float, unit: str) -> float:
    return round(value_in_meters if unit == "m" else value_in_meters * 3.28084, 2)


def _scaled_area_value(value_in_square_meters: float, unit: str) -> float:
    return round(value_in_square_meters if unit == "m" else value_in_square_meters * 10.7639, 2)


def _bound(value: float, minimum: float, maximum: float) -> float:
    return round(max(minimum, min(value, maximum)), 2)
