"""Kernel multi-room path (cascade stage D — the kernel).

``build_scene`` gains a branch: a *solved* plan (≥2 placed rooms) builds a floor
slab per room plus the shared-partition wall solids; a single room (or an
unsolved graph) keeps the exact old path — four perimeter walls with real
window/door openings. These tests pin both, and that glTF still serializes.
"""

from __future__ import annotations

from app.services.layout_solver import (
    apply_layout_to_graph,
    program_from_graph,
    solve_layout,
)
from app.services.spatial.gltf import scene_to_gltf
from app.services.spatial.kernel import build_scene


def _solved_apartment_graph():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "area": 24},
            {"id": "kitchen", "name": "Kitchen", "area": 12},
            {"id": "bed", "name": "Bed", "area": 14},
            {"id": "bath", "name": "Bath", "area": 5, "max_aspect": 2.6},
        ],
        "adjacencies": [["living", "kitchen"], ["living", "bed"], ["bed", "bath"]],
    }
    solution = solve_layout(program_from_graph(graph, seed=0))
    return apply_layout_to_graph(graph, solution), solution


# ── Single-room path is unchanged ─────────────────────────────────────────


def test_single_room_still_floor_plus_four_walls():
    graph = {"spaces": [{"id": "only", "dimensions": {"length": 5, "width": 4, "height": 2.8, "unit": "m"}}]}
    solids, _bbox, kind = build_scene(graph)
    assert kind == "interior"
    assert len([s for s in solids if s.type == "floor"]) == 1
    assert len([s for s in solids if s.type == "wall"]) == 4  # four perimeter walls


# ── Multi-room path ───────────────────────────────────────────────────────


def test_multiroom_builds_floor_per_room_and_partition_walls():
    graph, _ = _solved_apartment_graph()
    solids, bbox, kind = build_scene(graph)

    assert kind == "interior"
    floors = [s for s in solids if s.type == "floor"]
    walls = [s for s in solids if s.type == "wall"]
    assert len(floors) == 4                    # one slab per room
    assert len(walls) >= 4                      # perimeter + partitions
    # a partition wall is labelled with the two rooms it separates
    assert any("/" in s.name for s in walls)

    # every solid meshed cleanly (real Manifold geometry, not empty)
    for s in solids:
        assert s.verts is not None and len(s.verts) > 0
        assert s.tris is not None and len(s.tris) > 0

    lo_x, lo_y, lo_z, hi_x, hi_y, hi_z = bbox
    assert hi_x > lo_x and hi_z > lo_z          # finite footprint
    assert hi_y > 2.0                            # walls give it height


def test_multiroom_scene_serializes_to_gltf():
    graph, _ = _solved_apartment_graph()
    data = scene_to_gltf(graph)
    assert data and len(data) > 0
    # glb binary header or a JSON glTF — either is a valid serialization
    assert data[:4] == b"glTF" or b"mesh" in data[:2000].lower()


def test_multiroom_floor_count_tracks_room_count():
    graph, solution = _solved_apartment_graph()
    solids, _bbox, _kind = build_scene(graph)
    assert len([s for s in solids if s.type == "floor"]) == len(solution.rooms)
