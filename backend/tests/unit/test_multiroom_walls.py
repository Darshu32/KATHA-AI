"""Multi-room partition-aware wall derivation (cascade stage C).

The one thing that must be true: a wall shared by two rooms is emitted ONCE (a
partition tagged with both), never twice; an edge facing outside is an exterior
segment tagged with its single room; and a T-junction / partial overlap splits
into the right mix of the two. These tests pin that on hand-built plans where
the answer is countable by eye, then check the invariants on a solved plan.
"""

from __future__ import annotations

import pytest

from app.services.layout_solver import (
    LayoutProgram,
    RoomSpec,
    apply_layout_to_graph,
    program_from_graph,
    solve_layout,
)
from app.services.spatial_resolver import resolve_spatial_model
from app.services.wall_model import derive_multiroom_wall_model


def _room(rid, x, z, length, width, height=2.7):
    return {"id": rid, "x": x, "z": z, "length": length, "width": width, "height": height}


def _partitions(segs):
    return [s for s in segs if s["kind"] == "partition"]


def _exteriors(segs):
    return [s for s in segs if s["kind"] == "exterior"]


def _pairs(segs):
    return {frozenset(s["rooms"]) for s in _partitions(segs)}


# ── Degenerate / single ───────────────────────────────────────────────────


def test_single_room_is_four_exterior_walls():
    segs = derive_multiroom_wall_model([_room("A", 0, 0, 4, 3)])
    assert _partitions(segs) == []
    assert len(_exteriors(segs)) == 4
    assert all(s["rooms"] == ["A"] for s in segs)
    # one wall per side: two vertical (runs z) + two horizontal (runs x)
    assert sum(s["runs"] == "z" for s in segs) == 2
    assert sum(s["runs"] == "x" for s in segs) == 2


# ── Two rooms sharing one wall ────────────────────────────────────────────


def test_side_by_side_share_exactly_one_partition():
    segs = derive_multiroom_wall_model([_room("A", 0, 0, 4, 3), _room("B", 4, 0, 4, 3)])
    parts = _partitions(segs)
    assert len(parts) == 1                       # ONE shared wall, not two
    p = parts[0]
    assert p["runs"] == "z" and p["at"] == pytest.approx(4.0)
    assert p["start"] == pytest.approx(0.0) and p["end"] == pytest.approx(3.0)
    assert p["rooms"] == ["A", "B"]
    assert len(_exteriors(segs)) == 6            # 2 side + 4 (each room's top/bottom)


# ── Invariants ────────────────────────────────────────────────────────────


def test_partition_has_two_rooms_exterior_has_one():
    segs = derive_multiroom_wall_model([_room("A", 0, 0, 4, 3), _room("B", 4, 0, 4, 3)])
    for s in segs:
        assert len(s["rooms"]) == (2 if s["kind"] == "partition" else 1)
        assert len(s["rooms"]) == len(set(s["rooms"]))  # the two ids are distinct


def test_no_duplicated_walls():
    segs = derive_multiroom_wall_model(
        [_room("A", 0, 0, 4, 3), _room("B", 4, 0, 4, 3), _room("C", 0, 3, 8, 3)]
    )
    keys = [(s["runs"], s["at"], s["start"], s["end"], frozenset(s["rooms"])) for s in segs]
    assert len(keys) == len(set(keys))  # every segment is geometrically unique


# ── 2×2 grid: the interior cross ──────────────────────────────────────────


def test_two_by_two_grid_has_four_partitions():
    segs = derive_multiroom_wall_model([
        _room("A", 0, 0, 4, 3), _room("B", 4, 0, 4, 3),
        _room("C", 0, 3, 4, 3), _room("D", 4, 3, 4, 3),
    ])
    assert _pairs(segs) == {
        frozenset({"A", "B"}), frozenset({"C", "D"}),
        frozenset({"A", "C"}), frozenset({"B", "D"}),
    }
    assert len(_partitions(segs)) == 4  # no doubling


# ── T-junction: one big room against a shorter neighbour ──────────────────


def test_t_junction_splits_into_partition_and_exterior():
    # A spans z 0..6 on the left; B only 0..3 on the right. A's east edge is a
    # partition where B backs it (0..3) and exterior above B (3..6).
    segs = derive_multiroom_wall_model([_room("A", 0, 0, 4, 6), _room("B", 4, 0, 4, 3)])
    parts = _partitions(segs)
    assert len(parts) == 1
    assert parts[0]["rooms"] == ["A", "B"]
    assert parts[0]["at"] == pytest.approx(4.0)
    assert (parts[0]["start"], parts[0]["end"]) == pytest.approx((0.0, 3.0))

    # exactly the upper half of that line is A's exterior wall
    ext_at_4 = [s for s in _exteriors(segs) if s["runs"] == "z" and s["at"] == pytest.approx(4.0)]
    assert len(ext_at_4) == 1
    assert ext_at_4[0]["rooms"] == ["A"]
    assert (ext_at_4[0]["start"], ext_at_4[0]["end"]) == pytest.approx((3.0, 6.0))


# ── Centerline + height ───────────────────────────────────────────────────


def test_partition_sits_on_the_shared_line_and_takes_taller_height():
    segs = derive_multiroom_wall_model(
        [_room("A", 0, 0, 4, 3, height=2.7), _room("B", 4, 0, 4, 3, height=3.2)]
    )
    p = _partitions(segs)[0]
    assert p["at"] == pytest.approx(4.0)       # centered on the shared boundary
    assert p["height"] == pytest.approx(3.2)   # spans the taller of the two rooms


# ── End-to-end through the resolver, tied to solver adjacencies ───────────


def test_resolver_emits_segments_and_covers_satisfied_adjacencies():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "area": 24},
            {"id": "kitchen", "name": "Kitchen", "area": 12},
            {"id": "bed", "name": "Bed", "area": 14},
            {"id": "bath", "name": "Bath", "area": 5, "max_aspect": 2.6},
        ],
        "adjacencies": [["living", "kitchen"], ["living", "bed"], ["bed", "bath"]],
    }
    program = program_from_graph(graph, seed=0)
    solution = solve_layout(program)
    model = resolve_spatial_model(apply_layout_to_graph(graph, solution))

    assert model.wall_segments, "multi-room plan should yield wall segments"
    # Invariants hold on the typed model too.
    for s in model.wall_segments:
        assert len(s.rooms) == (2 if s.kind == "partition" else 1)
        assert s.length > 0

    # Every adjacency the solver satisfied must show up as a real shared wall.
    pairs = {frozenset(s.rooms) for s in model.wall_segments if s.kind == "partition"}
    for a, b in solution.satisfied_adjacencies:
        assert frozenset({a, b}) in pairs, f"no partition wall between {a} and {b}"
