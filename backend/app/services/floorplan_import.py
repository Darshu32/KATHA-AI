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
import math

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
                    "bbox": {
                        "type": "object",
                        "description": "the room's bounding rectangle in the IMAGE, as fractions of image size (top-left origin, x/y = top-left corner, w/h = size). This is how KATHA rebuilds your ACTUAL layout — be accurate and keep rooms non-overlapping.",
                        "properties": {
                            "x": {"type": "number", "description": "left edge, 0..1 of image width"},
                            "y": {"type": "number", "description": "top edge, 0..1 of image height"},
                            "w": {"type": "number", "description": "width, 0..1 of image width"},
                            "h": {"type": "number", "description": "height, 0..1 of image height"},
                        },
                        "required": ["x", "y", "w", "h"],
                    },
                },
                "required": ["id", "type", "area_sqm", "bbox"],
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
        "plan_size": {
            "type": "object",
            "description": "the overall plan's real-world size in METRES — read labelled dimensions if present, otherwise estimate at a normal residential scale (a 2-BHK flat is ~8-11 m across).",
            "properties": {
                "width_m": {"type": "number", "description": "overall plan width in metres (image left→right)"},
                "depth_m": {"type": "number", "description": "overall plan depth in metres (image top→bottom)"},
            },
            "required": ["width_m", "depth_m"],
        },
        "notes": {"type": "string", "description": "anything ambiguous or assumed"},
    },
    "required": ["rooms", "adjacencies", "plan_size", "notes"],
}

_SYSTEM = (
    "You are an expert architect reading a 2D architectural floor plan. Identify "
    "every distinct room / space. For each, give a unique short id, a room type "
    "from the listed set, an approximate floor area in square metres, and its "
    "BOUNDING BOX in the image as fractions of the image size (x, y = top-left "
    "corner; w, h = size; all 0..1). The bounding box is critical: KATHA rebuilds "
    "the model at exactly these positions, so it must match where each room really "
    "sits in the plan — preserve the actual arrangement, do NOT rearrange, and keep "
    "boxes non-overlapping and roughly tiling the plan. Read labelled dimensions "
    "when present, otherwise estimate at a normal residential/commercial scale; "
    "also give the plan's overall real-world width and depth in metres. Then list "
    "the adjacencies: pairs of room ids that share a wall with a door/opening "
    "(connect rooms through the hall/corridor/foyer). Be faithful to the plan's "
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


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _valid_bbox(b) -> bool:
    return isinstance(b, dict) and _f(b.get("w")) > 0 and _f(b.get("h")) > 0


def _placed(graph: dict) -> bool:
    return any(isinstance(s.get("position"), dict)
               for s in (graph.get("spaces") or []) if isinstance(s, dict))


def _plan_dimensions(rooms: list[dict], plan_size) -> tuple[float, float]:
    """Real-world plan ``(width_m, depth_m)`` — prefer the vision's ``plan_size``,
    else derive it from room areas vs their normalised bbox areas (median plan
    area) and the bbox extent's aspect ratio."""
    if isinstance(plan_size, dict):
        w, d = _f(plan_size.get("width_m")), _f(plan_size.get("depth_m"))
        if w > 0.5 and d > 0.5:
            return w, d
    boxes = [r["bbox"] for r in rooms if _valid_bbox(r.get("bbox"))]
    est = [_f(r["area_sqm"]) / (_f(r["bbox"]["w"]) * _f(r["bbox"]["h"]))
           for r in rooms if _valid_bbox(r.get("bbox")) and _f(r.get("area_sqm")) > 0]
    if not boxes or not est:
        return 0.0, 0.0
    total = sorted(est)[len(est) // 2]                        # median total plan area (m²)
    ew = max(_f(b["x"]) + _f(b["w"]) for b in boxes) - min(_f(b["x"]) for b in boxes)
    eh = max(_f(b["y"]) + _f(b["h"]) for b in boxes) - min(_f(b["y"]) for b in boxes)
    aspect = (ew or 1.0) / (eh or 1.0)
    return math.sqrt(total * aspect), math.sqrt(total / aspect)


def _place_from_bboxes(graph: dict, rooms: list[dict], plan_size) -> bool:
    """Place each space where the plan draws it: position + dimensions from its
    image bbox × the plan's real size, shifted so the layout's min corner sits at
    the origin. Image x → world x (length), image y → world z (width/depth). No-op
    (returns False, leaving the graph unplaced for the solver) unless EVERY room
    resolves — so a partial / garbled vision read falls back to a fresh solve."""
    spaces = [s for s in (graph.get("spaces") or []) if isinstance(s, dict)]
    if len(spaces) < 2 or not all(_valid_bbox(r.get("bbox")) for r in rooms):
        return False
    w_m, d_m = _plan_dimensions(rooms, plan_size)
    if w_m <= 0 or d_m <= 0:
        return False
    by_id = {r["id"]: r for r in rooms}
    placed: list[tuple] = []
    for s in spaces:
        r = by_id.get(str(s.get("id")))
        if not r or not _valid_bbox(r.get("bbox")):
            return False
        b = r["bbox"]
        placed.append((s, _f(b["x"]) * w_m, _f(b["y"]) * d_m, _f(b["w"]) * w_m, _f(b["h"]) * d_m))
    min_x = min(p[1] for p in placed)
    min_z = min(p[2] for p in placed)
    for s, x, z, length, width in placed:
        s["position"] = {"x": round(x - min_x, 3), "y": 0.0, "z": round(z - min_z, 3)}
        s["dimensions"] = {"length": round(max(length, 0.5), 3), "width": round(max(width, 0.5), 3),
                           "height": 2.8, "unit": "m"}
    logger.info("floorplan_import: layout-faithful placement of %d rooms (plan %.1f×%.1f m)",
                len(placed), w_m, d_m)
    return True


def build_multiroom_graph(program: dict, project_id: str, style: str | None) -> tuple[dict, object]:
    """Room program → furnished multi-room graph. When the vision returned each
    room's bbox + the plan size, rooms are placed EXACTLY where the plan draws them
    (layout-faithful) and the solver is skipped; otherwise the solver lays out a
    fresh plan from the room list (spec-first fallback). Returns (graph, solution)."""
    rooms = [r for r in (program.get("rooms") or []) if isinstance(r, dict) and r.get("id")]
    seen: set[str] = set()
    clean: list[dict] = []
    for r in rooms:
        rid = str(r["id"])
        if rid in seen:
            continue
        seen.add(rid)
        clean.append({"id": rid, "type": str(r.get("type") or "room"),
                      "area_sqm": _f(r.get("area_sqm")) or 12.0, "bbox": r.get("bbox")})

    primary = max(clean, key=lambda r: r["area_sqm"], default={"type": "living_room"})
    data = {
        "room": {"type": primary.get("type", "living_room"),
                 "dimensions": {"length": 6, "width": 4, "height": 2.8}},
        "rooms": [{"id": r["id"], "type": r["type"], "area_sqm": r["area_sqm"]} for r in clean],
        "adjacencies": [a for a in (program.get("adjacencies") or []) if isinstance(a, dict)],
        "style": {"primary": style or "modern", "secondary": [], "color_palette": [], "materials": []},
        "objects": [], "materials": [], "lighting": [],
        "render_prompt_2d": "", "render_prompt_3d": "",
    }
    graph = _ai_response_to_design_graph(data, project_id).model_dump()

    # Layout-faithful placement first; a fresh solve only when the plan geometry
    # couldn't be read. maybe_solve_layout no-ops on an already-placed graph.
    _place_from_bboxes(graph, clean, program.get("plan_size"))
    solved, solution = maybe_solve_layout(graph)
    if solution is not None or _placed(solved):
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
