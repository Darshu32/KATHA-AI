"""AI Orchestration — converts user prompts into structured design graphs via OpenAI."""

import json
import logging

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


# ── JSON schema for structured output ────────────────────────────────────────

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
                        "id", "type", "name", "position", "rotation",
                        "dimensions", "material", "color",
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
            "room", "style", "objects", "materials",
            "lighting", "render_prompt_2d", "render_prompt_3d",
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
    """Call OpenAI with structured output to produce a design graph from a prompt."""

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
    """Map the AI structured output to our internal DesignGraph model."""

    from app.models.design_graph import (
        AssetBundle,
        DesignGraph,
        SiteInfo,
        StyleProfile,
    )

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
    """Edit a single object in the design graph via a prompt."""

    client = _get_client()

    # Find the target object
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

    # Merge back into graph
    for i, obj in enumerate(current_graph["objects"]):
        if obj.get("id") == object_id:
            current_graph["objects"][i] = updated_obj
            break

    return current_graph


async def switch_theme(
    current_graph: dict,
    new_style: str,
    preserve_layout: bool = True,
) -> dict:
    """Apply a new theme/style to the entire design graph."""

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
