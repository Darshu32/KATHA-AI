"""Floor-plan image → multi-room design (Layer 5B, upload → geometry).

A vision LLM READS an uploaded floor plan and emits a ROOM PROGRAM (room
types + approximate areas + adjacencies). That program flows into the SAME
multi-room pipeline a text prompt uses — layout solver → kernel → render /
drawings — so an architect's existing plan becomes a modelled, solved,
furnished, dimensioned design.

This is spec-first, not a pixel-perfect trace: the vision model recovers the
*program* (what rooms, how big, what connects), and the deterministic solver
lays it out. That's the tractable, robust path vs. classical CV wall-tracing,
and it reuses the whole multi-room stack.
"""

from __future__ import annotations

import logging

from app.services.ai_orchestrator import _ai_response_to_design_graph
from app.services.layout_solver.furnish import furnish_rooms
from app.services.layout_solver.pipeline import maybe_solve_layout
from app.vision.base import VisionImage, VisionRequest
from app.vision.factory import get_vision_provider

logger = logging.getLogger(__name__)

# The room program the vision model must return — same shape the LLM emits from
# a text prompt (see ai_orchestrator._ai_response_to_design_graph), so it feeds
# the identical multi-room path.
ROOM_PROGRAM_SCHEMA = {
    "type": "object",
    "properties": {
        "rooms": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "unique short id, e.g. 'living', 'master', 'bath1'"},
                    "type": {"type": "string", "description": "living_room | kitchen | bedroom | master_bedroom | bathroom | toilet | dining | hall | corridor | foyer | balcony | study | office | utility | store"},
                    "area_sqm": {"type": "number", "description": "approximate floor area in square metres"},
                },
                "required": ["id", "type", "area_sqm"],
            },
        },
        "adjacencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a", "b"],
            },
            "description": "pairs of room ids that share a wall with a door/opening between them",
        },
        "notes": {"type": "string", "description": "anything ambiguous or assumed"},
    },
    "required": ["rooms", "adjacencies", "notes"],
}

_SYSTEM = (
    "You are an expert architect reading a 2D architectural floor plan. Identify "
    "every distinct room / space. For each, give a unique short id, a room type "
    "from the listed set, and an approximate floor area in square metres — read "
    "labelled dimensions when present, otherwise estimate from relative size at a "
    "normal residential/commercial scale. Then list the adjacencies: pairs of room "
    "ids that share a wall with a door or opening between them (include the "
    "hall/corridor/foyer and connect rooms through it). Be faithful to the plan's "
    "actual room count and layout; do not invent rooms that are not drawn."
)


async def extract_room_program(image: bytes, mime_type: str) -> dict:
    """Vision LLM → {rooms, adjacencies, notes}. Raises VisionError on failure."""
    provider = get_vision_provider()
    req = VisionRequest(
        images=[VisionImage(data=image, mime_type=mime_type, label="floor plan")],
        system_prompt=_SYSTEM,
        user_message="Read this floor plan and extract its room program as JSON.",
        output_schema=ROOM_PROGRAM_SCHEMA,
        purpose="floorplan_rooms",
        max_tokens=1800,
        temperature=0.1,
    )
    result = await provider.analyze(req)
    return result.parsed


def build_multiroom_graph(program: dict, project_id: str, style: str | None) -> tuple[dict, object]:
    """Room program → solved + furnished multi-room graph, via the SAME builder +
    layout solver the text-prompt path uses. Returns (graph_dict, solution|None)."""
    rooms = [r for r in (program.get("rooms") or []) if isinstance(r, dict) and r.get("id")]
    # de-dup ids and drop non-positive areas defensively
    seen: set[str] = set()
    clean: list[dict] = []
    for r in rooms:
        rid = str(r["id"])
        if rid in seen:
            continue
        seen.add(rid)
        area = float(r.get("area_sqm") or 0) or 12.0
        clean.append({"id": rid, "type": str(r.get("type") or "room"), "area_sqm": area})

    primary = max(clean, key=lambda r: r["area_sqm"], default={"type": "living_room"})
    data = {
        "room": {"type": primary.get("type", "living_room"),
                 "dimensions": {"length": 6, "width": 4, "height": 2.8}},
        "rooms": clean,
        "adjacencies": [a for a in (program.get("adjacencies") or []) if isinstance(a, dict)],
        "style": {"primary": style or "modern", "secondary": [], "color_palette": [], "materials": []},
        "objects": [], "materials": [], "lighting": [],
        "render_prompt_2d": "", "render_prompt_3d": "",
    }
    graph = _ai_response_to_design_graph(data, project_id).model_dump()
    solved, solution = maybe_solve_layout(graph)
    if solution is not None:
        solved = furnish_rooms(solved)
    return solved, solution


async def floorplan_to_design(
    image: bytes, mime_type: str, project_id: str, style: str | None = None,
) -> tuple[dict, dict, object]:
    """Floor-plan image → (solved multi-room graph, extracted program, solution)."""
    program = await extract_room_program(image, mime_type)
    graph, solution = build_multiroom_graph(program, project_id, style)
    logger.info("floorplan_import: %d rooms extracted, solved=%s",
                len(program.get("rooms") or []), solution is not None)
    return graph, program, solution
