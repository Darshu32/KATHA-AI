"""Bridge the solver's ``LayoutSolution`` into the typed spatial model.

``adapter.py`` writes a solution back into the loose ``DesignGraph`` (the path
the pipeline uses); this converts straight to the typed ``RoomPlacement`` list
for callers that already hold a solution and want typed geometry without a
graph round-trip. Kept separate so the core solver stays free of any dependency
on ``app.models``.
"""

from __future__ import annotations

from app.models.spatial_spec import RoomEnvelope, RoomPlacement, Vec3

from .models import LayoutSolution

_DEFAULT_HEIGHT = 2.8  # m — a room's height isn't a layout concern; assumed here


def placements_from_solution(
    solution: LayoutSolution,
    heights: dict[str, float] | None = None,
    default_height: float = _DEFAULT_HEIGHT,
) -> list[RoomPlacement]:
    """Solved rooms → typed :class:`RoomPlacement` list.

    ``heights`` supplies a per-room ceiling height (metres) where known; rooms
    absent from it fall back to ``default_height``.
    """
    heights = heights or {}
    return [
        RoomPlacement(
            id=room.id,
            name=room.name,
            position=Vec3(x=room.x, y=0.0, z=room.z),
            envelope=RoomEnvelope(
                length=room.length,
                width=room.width,
                height=heights.get(room.id, default_height),
            ),
        )
        for room in solution.rooms
    ]
