"""AI orchestration for prompt-to-design-graph flows."""

import json
import logging
from copy import deepcopy

from openai import AsyncOpenAI

from app.config import get_settings
from app.models.design_graph import DesignGraph
from app.prompts.design_graph import DESIGN_GRAPH_SYSTEM_PROMPT

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _has_openai_config() -> bool:
    return bool(settings.openai_api_key and settings.openai_api_key.strip())


DESIGN_GRAPH_JSON_SCHEMA = {
    "name": "design_graph",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "room": {
                "type": "object",
                "properties": {
                    "type": {"type": "string"},
                    "dimensions": {
                        "type": "object",
                        "properties": {
                            "length": {"type": "number"},
                            "width": {"type": "number"},
                            "height": {"type": "number"},
                        },
                        "required": ["length", "width", "height"],
                        "additionalProperties": False,
                    },
                },
                "required": ["type", "dimensions"],
                "additionalProperties": False,
            },
            "style": {
                "type": "object",
                "properties": {
                    "primary": {"type": "string"},
                    "secondary": {"type": "array", "items": {"type": "string"}},
                    "color_palette": {"type": "array", "items": {"type": "string"}},
                    "materials": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["primary", "secondary", "color_palette", "materials"],
                "additionalProperties": False,
            },
            "objects": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "name": {"type": "string"},
                        "position": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"},
                            },
                            "required": ["x", "y", "z"],
                            "additionalProperties": False,
                        },
                        "rotation": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"},
                            },
                            "required": ["x", "y", "z"],
                            "additionalProperties": False,
                        },
                        "dimensions": {
                            "type": "object",
                            "properties": {
                                "length": {"type": "number"},
                                "width": {"type": "number"},
                                "height": {"type": "number"},
                            },
                            "required": ["length", "width", "height"],
                            "additionalProperties": False,
                        },
                        "material": {"type": "string"},
                        "color": {"type": "string"},
                    },
                    "required": [
                        "id",
                        "type",
                        "name",
                        "position",
                        "rotation",
                        "dimensions",
                        "material",
                        "color",
                    ],
                    "additionalProperties": False,
                },
            },
            "materials": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "category": {"type": "string"},
                        "color": {"type": "string"},
                    },
                    "required": ["id", "name", "category", "color"],
                    "additionalProperties": False,
                },
            },
            "lighting": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "type": {"type": "string"},
                        "position": {
                            "type": "object",
                            "properties": {
                                "x": {"type": "number"},
                                "y": {"type": "number"},
                                "z": {"type": "number"},
                            },
                            "required": ["x", "y", "z"],
                            "additionalProperties": False,
                        },
                        "intensity": {"type": "number"},
                        "color": {"type": "string"},
                    },
                    "required": ["id", "type", "position", "intensity", "color"],
                    "additionalProperties": False,
                },
            },
            "render_prompt_2d": {"type": "string"},
            "render_prompt_3d": {"type": "string"},
        },
        "required": [
            "room",
            "style",
            "objects",
            "materials",
            "lighting",
            "render_prompt_2d",
            "render_prompt_3d",
        ],
        "additionalProperties": False,
    },
}


async def generate_design_graph(
    prompt: str,
    room_type: str = "living_room",
    style: str = "modern",
    project_id: str = "proj_new",
) -> DesignGraph:
    if not _has_openai_config():
        logger.warning(
            "OPENAI_API_KEY is not configured. Using local starter design graph."
        )
        return _build_local_design_graph(
            prompt=prompt,
            room_type=room_type,
            style=style,
            project_id=project_id,
        )

    client = _get_client()
    user_message = (
        f"Design prompt: {prompt}\n"
        f"Room type: {room_type}\n"
        f"Style/theme: {style}\n\n"
        "Generate the full structured design graph JSON."
    )

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": DESIGN_GRAPH_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": DESIGN_GRAPH_JSON_SCHEMA,
        },
        temperature=0.7,
        max_tokens=4096,
    )

    raw = response.choices[0].message.content
    data = json.loads(raw)
    logger.info("AI design graph generated for project %s", project_id)
    return _ai_response_to_design_graph(data, project_id)


def _ai_response_to_design_graph(data: dict, project_id: str) -> DesignGraph:
    from app.models.design_graph import AssetBundle, DesignGraph, SiteInfo, StyleProfile

    room = data.get("room", {})
    style_data = data.get("style", {})
    dims = room.get("dimensions", {})

    return DesignGraph(
        project_id=project_id,
        version=1,
        design_type="interior",
        style=StyleProfile(
            primary=style_data.get("primary", "modern"),
            secondary=style_data.get("secondary", []),
        ),
        site=SiteInfo(unit="metric"),
        spaces=[
            {
                "id": "space_001",
                "name": room.get("type", "Room"),
                "room_type": room.get("type", "living_room"),
                "dimensions": dims,
                "objects": [obj["id"] for obj in data.get("objects", [])],
            }
        ],
        geometry=[],
        objects=data.get("objects", []),
        materials=data.get("materials", []),
        lighting=data.get("lighting", []),
        constraints=[],
        estimation={
            "status": "pending",
            "assumptions": ["Quantities will be computed after geometry is validated."],
        },
        assets=AssetBundle(
            render_2d=[],
            scene_3d=[],
            masks=[],
            render_prompt_2d=data.get("render_prompt_2d", ""),
            render_prompt_3d=data.get("render_prompt_3d", ""),
        ),
    )


async def edit_object_via_prompt(
    current_graph: dict,
    object_id: str,
    edit_prompt: str,
) -> dict:
    if not _has_openai_config():
        updated_graph = deepcopy(current_graph)
        for obj in updated_graph.get("objects", []):
            if obj.get("id") == object_id:
                metadata = obj.setdefault("metadata", {})
                metadata["last_edit_prompt"] = edit_prompt
                if "brick" in edit_prompt.lower():
                    obj["material"] = "mat_brick"
                    obj["color"] = "#9a5c45"
                elif "wood" in edit_prompt.lower():
                    obj["material"] = "mat_floor_oak"
                    obj["color"] = "#9b6b3d"
                break
        return updated_graph

    client = _get_client()

    target_obj = None
    for obj in current_graph.get("objects", []):
        if obj.get("id") == object_id:
            target_obj = obj
            break

    if target_obj is None:
        raise ValueError(f"Object {object_id} not found in design graph")

    user_message = (
        f"Current object:\n{json.dumps(target_obj, indent=2)}\n\n"
        f"Edit instruction: {edit_prompt}\n\n"
        "Return the updated object JSON only. Keep the same id and type. "
        "Only change what the instruction asks for."
    )

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an architecture design AI. You receive a design object "
                    "and an edit instruction. Return ONLY the updated object as valid JSON. "
                    "Preserve the object's id and type. Apply realistic changes."
                ),
            },
            {"role": "user", "content": user_message},
        ],
        response_format={"type": "json_object"},
        temperature=0.5,
        max_tokens=1024,
    )

    updated_obj = json.loads(response.choices[0].message.content)
    for index, obj in enumerate(current_graph["objects"]):
        if obj.get("id") == object_id:
            current_graph["objects"][index] = updated_obj
            break

    return current_graph


async def switch_theme(
    current_graph: dict,
    new_style: str,
    preserve_layout: bool = True,
) -> dict:
    if not _has_openai_config():
        updated_graph = deepcopy(current_graph)
        updated_graph["style"] = {
            "primary": new_style,
            "secondary": ["local-fallback"],
        }
        for obj in updated_graph.get("objects", []):
            if new_style == "spanish":
                obj["color"] = "#c96f4a" if obj.get("type") != "sofa" else "#efe2cf"
            elif new_style == "industrial":
                obj["color"] = "#6b6f76"
            elif new_style == "scandinavian":
                obj["color"] = "#d9d2c3"
        return updated_graph

    client = _get_client()

    instruction = (
        f"Current design graph:\n{json.dumps(current_graph, indent=2)}\n\n"
        f"Switch the theme/style to: {new_style}\n"
    )
    if preserve_layout:
        instruction += (
            "IMPORTANT: Preserve the room layout and furniture positions. "
            "Only change materials, colors, textures, and decorative elements "
            "to match the new style."
        )
    else:
        instruction += "You may adjust layout and furniture to better fit the new style."

    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an architecture design AI specializing in style transformations. "
                    "You receive a full design graph and a new style. Return the complete "
                    "updated design graph JSON with the new style applied."
                ),
            },
            {"role": "user", "content": instruction},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": DESIGN_GRAPH_JSON_SCHEMA,
        },
        temperature=0.7,
        max_tokens=4096,
    )

    return json.loads(response.choices[0].message.content)


def _build_local_design_graph(
    prompt: str,
    room_type: str,
    style: str,
    project_id: str,
) -> DesignGraph:
    material_presets = {
        "modern": [
            {"id": "mat_floor_oak", "name": "Oak Flooring", "category": "wood", "color": "#9b6b3d"},
            {"id": "mat_wall_paint", "name": "Warm White Paint", "category": "paint", "color": "#f2eee8"},
            {"id": "mat_sofa_fabric", "name": "Soft Beige Fabric", "category": "fabric", "color": "#d9c7b0"},
            {"id": "mat_rug_wool", "name": "Sand Wool Rug", "category": "fabric", "color": "#d8ccb9"},
            {"id": "mat_metal_dark", "name": "Dark Bronze Metal", "category": "metal", "color": "#5f5245"},
        ],
        "spanish": [
            {"id": "mat_floor_terracotta", "name": "Terracotta Tile", "category": "tile", "color": "#b85e3b"},
            {"id": "mat_wall_plaster", "name": "Lime Plaster", "category": "plaster", "color": "#f1dfc9"},
            {"id": "mat_wood_oak", "name": "Dark Oak Wood", "category": "wood", "color": "#7b5232"},
            {"id": "mat_rug_wool", "name": "Patterned Wool Rug", "category": "fabric", "color": "#d8b59c"},
            {"id": "mat_metal_dark", "name": "Aged Iron", "category": "metal", "color": "#594a3f"},
        ],
    }
    materials = material_presets.get(style, material_presets["modern"])

    room_name = room_type.replace("_", " ").title()
    dims = {"length": 15, "width": 12, "height": 10}
    objects = [
        {
            "id": "sofa_1",
            "type": "sofa",
            "name": "Main Sofa",
            "position": {"x": 4.5, "y": 0, "z": 8.5},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 7, "width": 3, "height": 3},
            "material": materials[2]["id"],
            "color": materials[2]["color"],
        },
        {
            "id": "table_1",
            "type": "coffee_table",
            "name": "Coffee Table",
            "position": {"x": 4.5, "y": 0, "z": 5.8},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 3.5, "width": 2, "height": 1.4},
            "material": materials[0]["id"],
            "color": materials[0]["color"],
        },
        {
            "id": "chair_1",
            "type": "chair",
            "name": "Accent Chair",
            "position": {"x": 9.2, "y": 0, "z": 6.5},
            "rotation": {"x": 0, "y": -0.6, "z": 0},
            "dimensions": {"length": 2.5, "width": 2.5, "height": 3},
            "material": materials[2]["id"],
            "color": materials[2]["color"],
        },
        {
            "id": "rug_1",
            "type": "rug",
            "name": "Area Rug",
            "position": {"x": 4.8, "y": 0.02, "z": 6.7},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 7.5, "width": 5.5, "height": 0.05},
            "material": "mat_rug_wool",
            "color": materials[3]["color"],
        },
        {
            "id": "console_1",
            "type": "media_console",
            "name": "Media Console",
            "position": {"x": 4.5, "y": 0, "z": 1.2},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 1.3, "width": 5.5, "height": 2},
            "material": materials[0]["id"],
            "color": materials[0]["color"],
        },
        {
            "id": "lamp_1",
            "type": "floor_lamp",
            "name": "Floor Lamp",
            "position": {"x": 10.5, "y": 0, "z": 8.2},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 1.2, "width": 1.2, "height": 5.8},
            "material": "mat_metal_dark",
            "color": materials[4]["color"],
        },
        {
            "id": "plant_1",
            "type": "plant",
            "name": "Indoor Plant",
            "position": {"x": 12.2, "y": 0, "z": 2.2},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 1.4, "width": 1.4, "height": 4.2},
            "material": materials[4]["id"],
            "color": "#758b57",
        },
        {
            "id": "art_1",
            "type": "wall_art",
            "name": "Wall Art",
            "position": {"x": 4.6, "y": 5.6, "z": 0.16},
            "rotation": {"x": 0, "y": 0, "z": 0},
            "dimensions": {"length": 0.1, "width": 3.8, "height": 2.1},
            "material": "mat_wall_paint",
            "color": "#d7b18f",
        },
    ]
    lighting = [
        {
            "id": "light_ambient_1",
            "type": "ambient",
            "position": {"x": 7.5, "y": 9.5, "z": 6},
            "intensity": 0.7,
            "color": "#fff4de",
        },
        {
            "id": "light_floor_1",
            "type": "point",
            "position": {"x": 10.5, "y": 5, "z": 8},
            "intensity": 0.4,
            "color": "#ffd7a8",
        },
    ]

    return _ai_response_to_design_graph(
        {
            "room": {"type": room_type, "dimensions": dims},
            "style": {
                "primary": style,
                "secondary": ["local-fallback", "starter-layout"],
                "color_palette": [material["color"] for material in materials],
                "materials": [material["name"] for material in materials],
            },
            "objects": objects,
            "materials": materials,
            "lighting": lighting,
            "render_prompt_2d": f"{style} {room_name} with warm, practical furniture based on prompt: {prompt}",
            "render_prompt_3d": f"{style} {room_name} 3D scene with realistic spacing and circulation.",
        },
        project_id=project_id,
    )
