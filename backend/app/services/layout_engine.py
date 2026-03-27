"""Layout stage for the design orchestration pipeline."""

from __future__ import annotations

import json
import logging
from math import fabs
from time import perf_counter

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None

REQUIRED_LAYOUT_FIELDS = (
    "layout_summary",
    "zones",
    "furniture",
    "spacing",
    "orientation",
)

LAYOUT_JSON_SCHEMA = {
    "name": "architectural_layout",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "layout_summary": {"type": "string"},
            "zones": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "purpose": {"type": "string"},
                        "position": {"type": "string"},
                    },
                    "required": ["name", "purpose", "position"],
                    "additionalProperties": False,
                },
            },
            "furniture": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string"},
                        "position": {"type": "string"},
                        "orientation": {"type": "string"},
                        "zone": {"type": "string"},
                    },
                    "required": ["type", "position", "orientation", "zone"],
                    "additionalProperties": False,
                },
            },
            "spacing": {
                "type": "object",
                "properties": {
                    "walkways": {"type": "string"},
                    "furniture_gaps": {"type": "string"},
                },
                "required": ["walkways", "furniture_gaps"],
                "additionalProperties": False,
            },
            "orientation": {
                "type": "object",
                "properties": {
                    "tv": {"type": "string"},
                    "window": {"type": "string"},
                },
                "required": ["tv", "window"],
                "additionalProperties": False,
            },
        },
        "required": list(REQUIRED_LAYOUT_FIELDS),
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """
You are a senior space planner and interior architect.
Return only valid JSON matching the requested schema.

Rules:
- Produce realistic, buildable placements.
- Maintain walking paths and do not block openings.
- Use room dimensions and spacing intelligently.
- Align with the concept and theme, especially spatial preferences.
- Prefer practical placements like sofa opposite TV, bed against a wall, and dining near center or daylight.
""".strip()

OBJECT_SIZE_DEFAULTS = {
    "sofa": {"width": 7.0, "depth": 3.0},
    "tv_unit": {"width": 5.0, "depth": 1.5},
    "coffee_table": {"width": 4.0, "depth": 2.0},
    "bed": {"width": 6.5, "depth": 5.0},
    "wardrobe": {"width": 6.0, "depth": 2.0},
    "dining_table": {"width": 5.0, "depth": 3.0},
    "chairs": {"width": 2.0, "depth": 2.0},
    "console": {"width": 5.0, "depth": 1.5},
    "side_table": {"width": 1.5, "depth": 1.5},
    "desk": {"width": 5.0, "depth": 2.5},
    "chair": {"width": 2.0, "depth": 2.0},
}

CLEARANCE_DEFAULTS = {
    "sofa": {"front": 3.0, "back": 0.5, "left": 1.5, "right": 1.5},
    "tv_unit": {"front": 5.0, "back": 0.25, "left": 1.0, "right": 1.0},
    "coffee_table": {"front": 1.5, "back": 1.5, "left": 1.0, "right": 1.0},
    "bed": {"front": 3.0, "back": 0.5, "left": 2.0, "right": 2.0},
    "wardrobe": {"front": 3.0, "back": 0.25, "left": 0.5, "right": 0.5},
    "dining_table": {"front": 3.0, "back": 3.0, "left": 2.0, "right": 2.0},
    "chairs": {"front": 2.0, "back": 1.0, "left": 0.5, "right": 0.5},
    "console": {"front": 2.5, "back": 0.25, "left": 0.5, "right": 0.5},
    "side_table": {"front": 1.0, "back": 0.5, "left": 0.5, "right": 0.5},
    "desk": {"front": 3.0, "back": 0.5, "left": 1.5, "right": 1.5},
    "chair": {"front": 2.0, "back": 1.0, "left": 0.5, "right": 0.5},
}


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _has_openai_config() -> bool:
    return bool(settings.openai_api_key and settings.openai_api_key.strip())


def build_layout_prompt(input_data: dict, theme_config: dict, concept_data: dict) -> str:
    prompt = f"""
Design a layout for a {input_data.get("room_type", "space")}.

Room dimensions:
{json.dumps(input_data.get("dimensions", {}))}

Concept summary:
{concept_data.get("concept_summary", "")}

Design intent:
{concept_data.get("design_intent", "")}

Spatial strategy:
{concept_data.get("spatial_strategy", "")}

Furniture strategy:
{concept_data.get("furniture_strategy", "")}

Theme:
{theme_config.get("style", "modern")} ({theme_config.get("style_intensity", "medium")})

Materials:
{", ".join(theme_config.get("materials", []))}

Furniture style:
{theme_config.get("furniture_style", "")}

Spatial preferences:
{json.dumps(theme_config.get("spatial_preferences", {}))}

DO:
{"; ".join(theme_config.get("dos", []))}

DO NOT:
{"; ".join(theme_config.get("donts", []))}

Requirements:
{input_data.get("requirements", "")}

Generate:
- layout_summary
- zones
- furniture placement
- spacing rules
- orientation
""".strip()
    logger.info(
        "layout_prompt_built",
        extra={"room_type": input_data.get("room_type"), "style": theme_config.get("style")},
    )
    return prompt


async def process(input_data: dict, theme_config: dict, concept_data: dict) -> dict:
    """
    Generate a structured layout plan from intake, theme, and concept guidance.
    Falls back to a deterministic layout when the LLM is unavailable or invalid.
    """
    logger.info(
        "layout_generation_started",
        extra={
            "room_type": input_data.get("room_type"),
            "style": theme_config.get("style"),
            "style_intensity": theme_config.get("style_intensity"),
        },
    )

    prompt = build_layout_prompt(input_data, theme_config, concept_data)

    if not _has_openai_config():
        logger.warning(
            "layout_failed",
            extra={"room_type": input_data.get("room_type"), "reason": "openai_api_key_missing"},
        )
        return _build_compatibility_layout(_build_fallback_layout(input_data, theme_config, concept_data), theme_config)

    last_error: Exception | None = None
    for attempt in range(1, 3):
        try:
            llm_layout = await _generate_layout_via_llm(prompt)
            normalized = _normalize_layout_output(llm_layout, input_data, theme_config, concept_data)
            logger.info(
                "layout_generated",
                extra={
                    "room_type": input_data.get("room_type"),
                    "style": theme_config.get("style"),
                    "attempt": attempt,
                    "source": "llm",
                },
            )
            return _build_compatibility_layout(normalized, theme_config)
        except Exception as exc:
            last_error = exc
            logger.error(
                "layout_failed",
                extra={
                    "room_type": input_data.get("room_type"),
                    "style": theme_config.get("style"),
                    "attempt": attempt,
                    "error": str(exc),
                },
            )

    logger.info(
        "layout_generated",
        extra={
            "room_type": input_data.get("room_type"),
            "style": theme_config.get("style"),
            "attempt": 2,
            "source": "fallback",
            "error": str(last_error) if last_error else None,
        },
    )
    return _build_compatibility_layout(_build_fallback_layout(input_data, theme_config, concept_data), theme_config)


async def _generate_layout_via_llm(prompt: str) -> dict:
    client = _get_client()
    started_at = perf_counter()
    logger.info("layout_llm_called", extra={"model": settings.openai_model})
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_schema", "json_schema": LAYOUT_JSON_SCHEMA},
        temperature=0.2,
        max_tokens=1200,
    )
    logger.info(
        "layout_llm_response_received",
        extra={
            "latency_ms": int((perf_counter() - started_at) * 1000),
            "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
        },
    )
    return json.loads(response.choices[0].message.content)


def _normalize_layout_output(layout: dict, input_data: dict, theme_config: dict, concept_data: dict) -> dict:
    fallback_layout = _build_fallback_layout(input_data, theme_config, concept_data)
    dimensions = _normalize_room_dimensions(input_data.get("dimensions", {}))
    grid = _build_grid(dimensions)
    normalized = {
        "room_type": input_data.get("room_type", "space"),
        "dimensions": dimensions,
        "layout_summary": _sanitize_text(layout.get("layout_summary")) or fallback_layout["layout_summary"],
        "zones": _normalize_zones(layout.get("zones")) or fallback_layout["zones"],
        "furniture": _normalize_furniture(layout.get("furniture")) or fallback_layout["furniture"],
        "spacing": _normalize_spacing(layout.get("spacing")) or fallback_layout["spacing"],
        "orientation": _normalize_orientation(layout.get("orientation")) or fallback_layout["orientation"],
        "grid": grid,
    }

    normalized["furniture"] = _apply_geometry(normalized["furniture"], normalized["dimensions"], normalized["grid"])
    logger.info("geometry_applied", extra={"room_type": normalized["room_type"], "objects": len(normalized["furniture"])})
    normalized["relationships"] = _build_relationships(normalized["furniture"])
    logger.info("relationships_built", extra={"room_type": normalized["room_type"], "relationships": len(normalized["relationships"])})
    warnings = _detect_warnings(normalized["furniture"], normalized["dimensions"])
    normalized["warnings"] = warnings
    normalized["explanations"] = _build_explanations(normalized["furniture"], concept_data, theme_config)
    normalized["layout_score"] = _score_layout(
        warnings=warnings,
        theme_config=theme_config,
        furniture=normalized["furniture"],
    )
    logger.info("warnings_detected", extra={"room_type": normalized["room_type"], "warnings": len(warnings)})

    _validate_layout_logic(normalized, input_data)
    logger.info(
        "layout_validated",
        extra={
            "room_type": normalized["room_type"],
            "warnings": len(warnings),
        },
    )
    logger.info(
        "layout_scored",
        extra={
            "room_type": normalized["room_type"],
            "layout_score": normalized["layout_score"],
        },
    )
    return normalized


def _build_fallback_layout(input_data: dict, theme_config: dict, concept_data: dict) -> dict:
    room_type = input_data.get("room_type", "space")
    dimensions = _normalize_room_dimensions(input_data.get("dimensions", {}))
    grid = _build_grid(dimensions)
    primary_zone_name = _default_zone_for_room(room_type)
    focal_wall = "north wall"
    window_side = "east"
    open_space = bool(theme_config.get("spatial_preferences", {}).get("open_space", True))
    clutter_level = theme_config.get("spatial_preferences", {}).get("clutter_level", "low")

    if room_type == "bedroom":
        furniture = [
            {"type": "bed", "position": "south wall", "orientation": f"facing {focal_wall}", "zone": "sleeping_area"},
            {"type": "wardrobe", "position": "west wall", "orientation": "parallel to wall", "zone": "storage_area"},
            {"type": "side_table", "position": "beside bed", "orientation": "aligned with bed", "zone": "sleeping_area"},
        ]
        zones = [
            {"name": "sleeping_area", "purpose": "rest and recovery", "position": "center"},
            {"name": "storage_area", "purpose": "organized storage", "position": "west"},
        ]
    elif room_type == "dining_room":
        furniture = [
            {"type": "dining_table", "position": "center", "orientation": "aligned with long axis", "zone": "dining_area"},
            {"type": "chairs", "position": "around table", "orientation": "facing inward", "zone": "dining_area"},
            {"type": "console", "position": "north wall", "orientation": "parallel to wall", "zone": "support_area"},
        ]
        zones = [
            {"name": "dining_area", "purpose": "shared dining", "position": "center"},
            {"name": "support_area", "purpose": "serving and display", "position": "north"},
        ]
    elif room_type == "office":
        furniture = [
            {"type": "desk", "position": "east wall", "orientation": f"facing {window_side}", "zone": "work_area"},
            {"type": "chair", "position": "center", "orientation": "toward desk", "zone": "work_area"},
            {"type": "console", "position": "north wall", "orientation": "parallel to wall", "zone": "storage_area"},
        ]
        zones = [
            {"name": "work_area", "purpose": "focused work", "position": "east"},
            {"name": "storage_area", "purpose": "organized storage", "position": "north"},
        ]
    else:
        furniture = [
            {"type": "sofa", "position": "center", "orientation": f"facing {focal_wall}", "zone": primary_zone_name},
            {"type": "tv_unit", "position": focal_wall, "orientation": "facing seating", "zone": primary_zone_name},
            {"type": "coffee_table", "position": "between sofa and tv", "orientation": "centered on seating axis", "zone": primary_zone_name},
        ]
        if not open_space and clutter_level != "low":
            furniture.append(
                {"type": "console", "position": "west wall", "orientation": "parallel to wall", "zone": primary_zone_name}
            )
        zones = [
            {"name": primary_zone_name, "purpose": _default_zone_purpose(room_type), "position": "center"},
            {"name": "circulation_zone", "purpose": "clear movement path", "position": "perimeter"},
        ]

    furniture = _apply_geometry(furniture, dimensions, grid)
    warnings = _detect_warnings(furniture, dimensions)
    relationships = _build_relationships(furniture)

    walkway_clearance = "minimum 3 ft clearance" if dimensions["unit"] == "ft" else "minimum 0.9 m clearance"
    furniture_gaps = "1-2 ft between elements" if dimensions["unit"] == "ft" else "0.3-0.6 m between elements"

    return {
        "room_type": room_type,
        "dimensions": dimensions,
        "grid": grid,
        "layout_summary": _fallback_layout_summary(input_data, theme_config, concept_data),
        "zones": zones,
        "furniture": furniture,
        "spacing": {"walkways": walkway_clearance, "furniture_gaps": furniture_gaps},
        "orientation": {
            "tv": focal_wall if any(item["type"] == "tv_unit" for item in furniture) else "not applicable",
            "window": window_side,
        },
        "relationships": relationships,
        "warnings": warnings,
        "explanations": _build_explanations(furniture, concept_data, theme_config),
        "layout_score": _score_layout(warnings=warnings, theme_config=theme_config, furniture=furniture),
    }


def _build_compatibility_layout(layout: dict, theme_config: dict) -> dict:
    dimensions = dict(layout.get("dimensions") or {})
    if "height" not in dimensions:
        dimensions["height"] = 10

    furniture_ids = []
    objects = []
    material_palette = theme_config.get("materials", ["paint", "wood_panel", "fabric"])
    color_palette = theme_config.get("palette", theme_config.get("colors", ["white", "beige", "grey"]))

    for index, item in enumerate(layout["furniture"], start=1):
        object_id = f"{item['type']}_{index}"
        furniture_ids.append(object_id)
        size = item["size"]
        coordinates = item["coordinates"]
        objects.append(
            {
                "id": object_id,
                "type": item["type"],
                "name": item["type"].replace("_", " ").title(),
                "dimensions": {
                    "length": size["width"],
                    "width": size["depth"],
                    "height": 2.5,
                },
                "position": {
                    "x": coordinates["x"],
                    "y": 0,
                    "z": coordinates["y"],
                },
                "rotation": {"x": 0, "y": item["rotation"], "z": 0},
                "material": material_palette[min(index - 1, len(material_palette) - 1)],
                "color": color_palette[min(index - 1, len(color_palette) - 1)],
                "zone": item["zone"],
                "orientation_label": item["orientation"],
                "clearance": item["clearance"],
            }
        )

    materials = [
        {
            "id": f"mat_{index}",
            "name": material,
            "category": material,
            "color": color_palette[min(index, len(color_palette) - 1)],
        }
        for index, material in enumerate(material_palette)
    ]

    return {
        **layout,
        "room_type": layout.get("room_type"),
        "dimensions": dimensions,
        "spaces": [
            {
                "id": "space_primary",
                "name": str(layout.get("room_type", "space")).replace("_", " ").title(),
                "room_type": layout.get("room_type"),
                "dimensions": dimensions,
                "objects": furniture_ids,
            }
        ],
        "objects": objects,
        "materials": materials,
        "lighting": [
            {
                "id": "ambient_main",
                "type": theme_config.get("lighting_style", theme_config.get("lighting", "balanced")),
                "position": {"x": dimensions["length"] / 2, "y": 8, "z": dimensions["width"] / 2},
                "intensity": 0.8,
                "color": color_palette[0],
            }
        ],
        "concept_summary": layout["layout_summary"],
        "theme_reference": theme_config,
        "graph_relationships": [
            {
                "from": rel["from"],
                "to": rel["to"],
                "type": rel["type"],
            }
            for rel in layout.get("relationships", [])
        ],
    }


def _normalize_room_dimensions(dimensions: dict) -> dict:
    return {
        "length": float(dimensions.get("length", 12)),
        "width": float(dimensions.get("width", 10)),
        "unit": str(dimensions.get("unit", "ft")),
        "height": float(dimensions.get("height", 10)),
    }


def _apply_geometry(furniture: list[dict], dimensions: dict, grid: dict) -> list[dict]:
    placed = []
    for item in furniture:
        size = _infer_object_size(item["type"], dimensions)
        coordinates = _derive_coordinates(item["position"], size, dimensions, placed, grid)
        placed.append(
            {
                **item,
                "size": size,
                "coordinates": coordinates,
                "rotation": _infer_rotation(item["orientation"]),
                "clearance": _infer_clearance(item["type"], dimensions),
            }
        )
    return placed


def _infer_object_size(object_type: str, room_dimensions: dict) -> dict:
    base = dict(OBJECT_SIZE_DEFAULTS.get(object_type, {"width": 2.5, "depth": 2.0}))
    max_width = max(room_dimensions["length"] * 0.45, 1.5)
    max_depth = max(room_dimensions["width"] * 0.35, 1.2)
    base["width"] = round(min(base["width"], max_width), 2)
    base["depth"] = round(min(base["depth"], max_depth), 2)
    return base


def _derive_coordinates(position: str, size: dict, room_dimensions: dict, placed: list[dict], grid: dict) -> dict:
    margin = 1.5 if room_dimensions["unit"] == "ft" else 0.45
    x_center = room_dimensions["length"] / 2
    y_center = room_dimensions["width"] / 2

    position_lower = position.lower()
    if "north" in position_lower:
        x = x_center
        y = margin + size["depth"] / 2
    elif "south" in position_lower:
        x = x_center
        y = room_dimensions["width"] - margin - size["depth"] / 2
    elif "east" in position_lower:
        x = room_dimensions["length"] - margin - size["width"] / 2
        y = y_center
    elif "west" in position_lower:
        x = margin + size["width"] / 2
        y = y_center
    elif "between" in position_lower and placed:
        anchor = placed[0]["coordinates"]
        x = anchor["x"]
        y = max(anchor["y"] - 2.0, margin + size["depth"] / 2)
    else:
        x = x_center
        y = y_center

    x = max(size["width"] / 2, min(round(x, 2), room_dimensions["length"] - size["width"] / 2))
    y = max(size["depth"] / 2, min(round(y, 2), room_dimensions["width"] - size["depth"] / 2))
    if grid["snap"]:
        x = _snap_to_grid(x, grid["unit"], minimum=size["width"] / 2, maximum=room_dimensions["length"] - size["width"] / 2)
        y = _snap_to_grid(y, grid["unit"], minimum=size["depth"] / 2, maximum=room_dimensions["width"] - size["depth"] / 2)
    return {"x": x, "y": y, "z": 0}


def _build_relationships(furniture: list[dict]) -> list[dict]:
    relationships: list[dict] = []
    items_by_type = {item["type"]: item for item in furniture}

    if "sofa" in items_by_type and "tv_unit" in items_by_type:
        relationships.append({"from": "sofa", "to": "tv_unit", "type": "facing"})
    if "coffee_table" in items_by_type and "sofa" in items_by_type:
        relationships.append({"from": "coffee_table", "to": "sofa", "type": "adjacent"})
    if "bed" in items_by_type and "side_table" in items_by_type:
        relationships.append({"from": "side_table", "to": "bed", "type": "near"})
    if "dining_table" in items_by_type and "chairs" in items_by_type:
        relationships.append({"from": "chairs", "to": "dining_table", "type": "aligned"})

    return relationships


def _detect_warnings(furniture: list[dict], dimensions: dict) -> list[str]:
    warnings: list[str] = []
    walkway_threshold = 3.0 if dimensions["unit"] == "ft" else 0.9

    for index, current in enumerate(furniture):
        if _distance_to_wall(current, dimensions) < walkway_threshold / 2:
            warnings.append(f"{current['type']} is too close to room perimeter for comfortable circulation")
        if not _clearance_within_room(current, dimensions):
            warnings.append(f"{current['type']} clearance exceeds available room boundary")
        if current["rotation"] not in {0, 90, 180, 270}:
            warnings.append(f"{current['type']} has non-standard rotation")
        if not _is_grid_aligned(current["coordinates"]["x"], dimensions) or not _is_grid_aligned(current["coordinates"]["y"], dimensions):
            warnings.append(f"{current['type']} is off grid alignment")

        for other in furniture[index + 1 :]:
            if _boxes_overlap(current, other):
                warnings.append(f"possible overlap between {current['type']} and {other['type']}")
            elif _distance_between(current, other) < walkway_threshold / 3:
                warnings.append(f"walkway below recommended clearance near {current['type']} and {other['type']}")

    return list(dict.fromkeys(warnings))


def _boxes_overlap(first: dict, second: dict) -> bool:
    return (
        fabs(first["coordinates"]["x"] - second["coordinates"]["x"]) < (first["size"]["width"] + second["size"]["width"]) / 2
        and fabs(first["coordinates"]["y"] - second["coordinates"]["y"]) < (first["size"]["depth"] + second["size"]["depth"]) / 2
    )


def _distance_between(first: dict, second: dict) -> float:
    x_gap = max(
        fabs(first["coordinates"]["x"] - second["coordinates"]["x"]) - (first["size"]["width"] + second["size"]["width"]) / 2,
        0,
    )
    y_gap = max(
        fabs(first["coordinates"]["y"] - second["coordinates"]["y"]) - (first["size"]["depth"] + second["size"]["depth"]) / 2,
        0,
    )
    return round(min(x_gap, y_gap), 2)


def _distance_to_wall(item: dict, dimensions: dict) -> float:
    left = item["coordinates"]["x"] - item["size"]["width"] / 2
    right = dimensions["length"] - (item["coordinates"]["x"] + item["size"]["width"] / 2)
    top = item["coordinates"]["y"] - item["size"]["depth"] / 2
    bottom = dimensions["width"] - (item["coordinates"]["y"] + item["size"]["depth"] / 2)
    return min(left, right, top, bottom)


def _score_layout(*, warnings: list[str], theme_config: dict, furniture: list[dict]) -> float:
    score = 1.0
    score -= min(len(warnings) * 0.1, 0.4)

    spatial_preferences = theme_config.get("spatial_preferences", {})
    if spatial_preferences.get("symmetry") == "high" and len(furniture) % 2 != 0:
        score -= 0.1
    if spatial_preferences.get("clutter_level") == "low" and len(furniture) > 4:
        score -= 0.1
    if spatial_preferences.get("open_space") and len(furniture) > 5:
        score -= 0.1

    return round(max(0.0, min(score, 1.0)), 2)


def _validate_layout_logic(layout: dict, input_data: dict) -> None:
    for field_name in REQUIRED_LAYOUT_FIELDS:
        if field_name not in layout:
            raise ValueError(f"Layout missing required field '{field_name}'")

    if not layout["layout_summary"]:
        raise ValueError("Layout summary must not be empty")

    zone_names = {zone["name"] for zone in layout["zones"]}
    if not zone_names:
        raise ValueError("Layout must contain at least one zone")

    room_length = float(input_data.get("dimensions", {}).get("length", 0) or 0)
    room_width = float(input_data.get("dimensions", {}).get("width", 0) or 0)
    if room_length <= 0 or room_width <= 0:
        raise ValueError("Room dimensions must be positive for layout generation")

    for item in layout["furniture"]:
        if item["zone"] not in zone_names:
            raise ValueError(f"Furniture zone '{item['zone']}' is not declared in zones")
        if item["coordinates"]["x"] < 0 or item["coordinates"]["x"] > room_length:
            raise ValueError(f"{item['type']} x coordinate is out of bounds")
        if item["coordinates"]["y"] < 0 or item["coordinates"]["y"] > room_width:
            raise ValueError(f"{item['type']} y coordinate is out of bounds")
        if item["coordinates"]["z"] != 0:
            raise ValueError(f"{item['type']} z coordinate must default to 0 at layout stage")
        if item["rotation"] not in {0, 90, 180, 270}:
            raise ValueError(f"{item['type']} rotation must be 0, 90, 180, or 270")
        if not _clearance_within_room(item, layout["dimensions"]):
            raise ValueError(f"{item['type']} clearance extends beyond room bounds")
        if layout["grid"]["snap"] and (
            not _is_grid_aligned(item["coordinates"]["x"], layout["dimensions"])
            or not _is_grid_aligned(item["coordinates"]["y"], layout["dimensions"])
        ):
            raise ValueError(f"{item['type']} is not aligned to the active grid")


def _normalize_zones(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    zones = []
    for item in value:
        if not isinstance(item, dict):
            continue
        zone = {
            "name": _sanitize_text(item.get("name")),
            "purpose": _sanitize_text(item.get("purpose")),
            "position": _sanitize_text(item.get("position")),
        }
        if all(zone.values()):
            zones.append(zone)
    return zones


def _normalize_furniture(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    furniture = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {
            "type": _sanitize_text(item.get("type")),
            "position": _sanitize_text(item.get("position")),
            "orientation": _sanitize_text(item.get("orientation")),
            "zone": _sanitize_text(item.get("zone")),
        }
        if all(normalized.values()):
            furniture.append(normalized)
    return furniture


def _normalize_spacing(value) -> dict:
    if not isinstance(value, dict):
        return {}
    normalized = {
        "walkways": _sanitize_text(value.get("walkways")),
        "furniture_gaps": _sanitize_text(value.get("furniture_gaps")),
    }
    return normalized if all(normalized.values()) else {}


def _normalize_orientation(value) -> dict:
    if not isinstance(value, dict):
        return {}
    normalized = {
        "tv": _sanitize_text(value.get("tv")),
        "window": _sanitize_text(value.get("window")),
    }
    return normalized if all(normalized.values()) else {}


def _sanitize_text(value) -> str:
    return " ".join(str(value or "").split()).strip()


def _fallback_layout_summary(input_data: dict, theme_config: dict, concept_data: dict) -> str:
    return (
        f"A practical {theme_config.get('style', 'modern')} layout for the {input_data.get('room_type', 'space')} "
        f"that follows the concept direction: {concept_data.get('spatial_strategy', '')}"
    ).strip()


def _default_zone_for_room(room_type: str) -> str:
    return {
        "living_room": "seating_area",
        "bedroom": "sleeping_area",
        "office": "work_area",
        "dining_room": "dining_area",
    }.get(room_type, "primary_area")


def _default_zone_purpose(room_type: str) -> str:
    return {
        "living_room": "social interaction",
        "office": "focused work",
        "bedroom": "rest and recovery",
        "dining_room": "shared dining",
    }.get(room_type, "daily use")


def _build_grid(dimensions: dict) -> dict:
    return {
        "unit": 1.0 if dimensions["unit"] == "ft" else 0.3,
        "snap": True,
    }


def _snap_to_grid(value: float, grid_unit: float, *, minimum: float, maximum: float) -> float:
    snapped = round(round(value / grid_unit) * grid_unit, 2)
    return max(round(minimum, 2), min(snapped, round(maximum, 2)))


def _infer_rotation(orientation: str) -> int:
    orientation = orientation.lower()
    if "north" in orientation:
        return 0
    if "east" in orientation:
        return 90
    if "south" in orientation:
        return 180
    if "west" in orientation:
        return 270
    if "aligned" in orientation or "parallel" in orientation:
        return 0
    return 0


def _infer_clearance(object_type: str, dimensions: dict) -> dict:
    base = dict(CLEARANCE_DEFAULTS.get(object_type, {"front": 2.0, "back": 0.5, "left": 0.5, "right": 0.5}))
    if dimensions["unit"] == "m":
        return {key: round(value * 0.3048, 2) for key, value in base.items()}
    return base


def _clearance_within_room(item: dict, dimensions: dict) -> bool:
    x = item["coordinates"]["x"]
    y = item["coordinates"]["y"]
    size = item["size"]
    clearance = item["clearance"]
    min_x = x - size["width"] / 2 - clearance["left"]
    max_x = x + size["width"] / 2 + clearance["right"]
    min_y = y - size["depth"] / 2 - clearance["back"]
    max_y = y + size["depth"] / 2 + clearance["front"]
    return min_x >= 0 and max_x <= dimensions["length"] and min_y >= 0 and max_y <= dimensions["width"]


def _is_grid_aligned(value: float, dimensions: dict) -> bool:
    grid = _build_grid(dimensions)
    remainder = round(value % grid["unit"], 4)
    half_step = round(grid["unit"] / 2, 4)
    return remainder in {0.0, half_step, round(grid["unit"], 4)}


def _build_explanations(furniture: list[dict], concept_data: dict, theme_config: dict) -> list[str]:
    explanations: list[str] = []
    spatial_preferences = theme_config.get("spatial_preferences", {})
    summary_hint = concept_data.get("spatial_strategy", "") or concept_data.get("furniture_strategy", "")

    for item in furniture:
        if item["type"] == "sofa":
            explanations.append("sofa placed centrally to support social interaction")
        elif item["type"] == "tv_unit":
            explanations.append("tv aligned for optimal viewing angle")
        elif item["type"] == "bed":
            explanations.append("bed placed near a wall to preserve calm circulation")
        elif item["type"] == "dining_table":
            explanations.append("dining table centered to support balanced movement around seating")

    if spatial_preferences.get("open_space"):
        explanations.append("layout preserves open space in response to the theme spatial preferences")
    if spatial_preferences.get("symmetry") == "high":
        explanations.append("major elements are aligned to support a more symmetrical composition")
    if summary_hint:
        explanations.append(f"layout decisions reflect the concept guidance: {summary_hint}")

    return list(dict.fromkeys(explanations))
