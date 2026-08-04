"""Deterministic layout solver — invariant + behaviour tests.

The slicing-tree representation is supposed to make three things *impossible*:
overlapping rooms, rooms that don't tile the boundary, and rooms whose area
drifts from target. These tests pin those invariants forever, then check the
soft objectives the annealer is responsible for (adjacency, proportion) and the
graph adapter round-trip.
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
from app.services.layout_solver.models import PlacedRoom

# A realistic ~90 m² three-bed apartment program.
_APARTMENT = LayoutProgram(
    rooms=[
        RoomSpec(id="living", name="Living", area=24),
        RoomSpec(id="kitchen", name="Kitchen", area=12),
        RoomSpec(id="master", name="Master Bed", area=16),
        RoomSpec(id="bed2", name="Bedroom 2", area=12),
        RoomSpec(id="bed3", name="Bedroom 3", area=10),
        RoomSpec(id="bath1", name="Bath 1", area=5),
        RoomSpec(id="bath2", name="Bath 2", area=4),
        RoomSpec(id="hall", name="Hall", area=7),
    ],
    adjacencies=[("hall", "living"), ("hall", "kitchen"), ("master", "bath1")],
    seed=0,
    iterations=4000,
)


def _overlap_area(a: PlacedRoom, b: PlacedRoom) -> float:
    dx = max(0.0, min(a.x + a.length, b.x + b.length) - max(a.x, b.x))
    dz = max(0.0, min(a.z + a.width, b.z + b.width) - max(a.z, b.z))
    return dx * dz


# ── Hard invariants (guaranteed by construction) ──────────────────────────


def test_no_two_rooms_overlap():
    sol = solve_layout(_APARTMENT)
    rooms = sol.rooms
    for i, a in enumerate(rooms):
        for b in rooms[i + 1 :]:
            assert _overlap_area(a, b) < 1e-6, f"{a.id} overlaps {b.id}"


def test_area_is_exact():
    sol = solve_layout(_APARTMENT)
    # Slicing dissection gives each room exactly its target area.
    assert sol.max_area_error < 1e-6
    targets = {r.id: r.area for r in _APARTMENT.rooms}
    for room in sol.rooms:
        assert room.area == pytest.approx(targets[room.id], rel=1e-6)


def test_rooms_tile_the_boundary():
    sol = solve_layout(_APARTMENT)
    bl, bw = sol.boundary
    covered = sum(r.area for r in sol.rooms)
    assert covered == pytest.approx(bl * bw, rel=1e-6)  # no gaps, no overhang
    for r in sol.rooms:  # every room inside the footprint
        assert r.x >= -1e-6 and r.z >= -1e-6
        assert r.x + r.length <= bl + 1e-6
        assert r.z + r.width <= bw + 1e-6


def test_all_rooms_present():
    sol = solve_layout(_APARTMENT)
    assert {r.id for r in sol.rooms} == {r.id for r in _APARTMENT.rooms}


# ── Determinism ───────────────────────────────────────────────────────────


def test_same_seed_is_reproducible():
    a = solve_layout(_APARTMENT)
    b = solve_layout(_APARTMENT)
    assert a.model_dump() == b.model_dump()


def test_seed_changes_the_search_but_not_validity():
    a = solve_layout(_APARTMENT.model_copy(update={"seed": 0}))
    b = solve_layout(_APARTMENT.model_copy(update={"seed": 7}))
    # Both are valid tilings; area stays exact regardless of the path taken.
    assert a.max_area_error < 1e-6 and b.max_area_error < 1e-6


# ── Soft objectives (the annealer's job) ──────────────────────────────────


def test_simple_adjacencies_fully_satisfied():
    # A definitely-slicible program: {A|B} and {C|D} as two halves.
    program = LayoutProgram(
        rooms=[
            RoomSpec(id="a", area=20),
            RoomSpec(id="b", area=20),
            RoomSpec(id="c", area=10),
            RoomSpec(id="d", area=10),
        ],
        adjacencies=[("a", "b"), ("c", "d")],
        seed=0,
    )
    sol = solve_layout(program)
    assert sol.unsatisfied_adjacencies == []
    assert sol.adjacency_satisfaction == 1.0


def test_apartment_adjacency_mostly_satisfied():
    sol = solve_layout(_APARTMENT)
    # The annealer should place most requested adjacencies; we don't demand a
    # perfect (possibly non-slicible) solution, only a strong one.
    assert sol.adjacency_satisfaction >= 0.66


def test_no_slivers_in_a_square_program():
    # Four equal rooms in a square boundary should come out near-square.
    program = LayoutProgram(
        rooms=[RoomSpec(id=f"r{i}", area=16, max_aspect=1.5) for i in range(4)],
        boundary=(8.0, 8.0),
        seed=0,
    )
    sol = solve_layout(program)
    for r in sol.rooms:
        assert r.aspect <= 1.6  # within the requested proportion


# ── Boundary handling ─────────────────────────────────────────────────────


def test_single_room_fills_boundary():
    program = LayoutProgram(rooms=[RoomSpec(id="only", area=20)], seed=0)
    sol = solve_layout(program)
    assert len(sol.rooms) == 1
    only = sol.rooms[0]
    assert only.area == pytest.approx(20, rel=1e-6)
    assert only.x == pytest.approx(0.0) and only.z == pytest.approx(0.0)


def test_explicit_boundary_is_used():
    program = LayoutProgram(
        rooms=[RoomSpec(id="a", area=30), RoomSpec(id="b", area=30)],
        boundary=(10.0, 6.0),
        seed=0,
    )
    sol = solve_layout(program)
    assert sol.boundary == (10.0, 6.0)


def test_derived_boundary_preserves_total_area():
    total = sum(r.area for r in _APARTMENT.rooms)
    sol = solve_layout(_APARTMENT)
    assert sol.boundary[0] * sol.boundary[1] == pytest.approx(total, rel=1e-6)


# ── Graph adapter ─────────────────────────────────────────────────────────


def test_program_from_graph_reads_spaces_and_adjacencies():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "dimensions": {"length": 6, "width": 4}},
            {"id": "kitchen", "name": "Kitchen", "area": 12},
            {"name": "Bath"},  # no id, no dims → default area, id from name
        ],
        "adjacencies": [{"a": "living", "b": "kitchen"}, ["kitchen", "Bath"]],
    }
    program = program_from_graph(graph, seed=3, iterations=500)
    assert [r.id for r in program.rooms] == ["living", "kitchen", "Bath"]
    assert program.rooms[0].area == pytest.approx(24)  # 6 × 4
    assert program.rooms[1].area == pytest.approx(12)
    assert program.adjacencies == [("living", "kitchen"), ("kitchen", "Bath")]
    assert program.seed == 3 and program.iterations == 500


def test_unstated_area_is_flagged_not_silent():
    # A room the graph says nothing about must NOT be silently assumed — the
    # assumption is surfaced on both the program and the solved plan.
    graph = {"spaces": [{"id": "mystery", "name": "Mystery"}, {"id": "kitchen", "area": 12}]}
    program = program_from_graph(graph)
    assert program.rooms[0].area == pytest.approx(12.0)  # fallback value applied
    assert any("mystery" in w and "no stated area" in w for w in program.warnings)
    assert len(program.warnings) == 1  # kitchen stated its area → no warning

    sol = solve_layout(program)
    assert any("mystery" in w for w in sol.warnings)  # carried onto the solution


def test_stated_areas_produce_no_warnings():
    graph = {"spaces": [{"id": "a", "dimensions": {"length": 5, "width": 4}}]}
    sol = solve_layout(program_from_graph(graph))
    assert sol.warnings == []


def test_program_from_graph_handles_mm_dimensions():
    graph = {"spaces": [{"id": "r", "dimensions": {"length": 4500, "width": 3000}}]}
    program = program_from_graph(graph)
    assert program.rooms[0].area == pytest.approx(13.5)  # 4.5 m × 3.0 m


def test_apply_layout_to_graph_is_additive():
    graph = {
        "project_id": "p1",
        "style": {"primary": "Modern"},
        "spaces": [
            {"id": "a", "name": "A", "prompt": "keep me"},
            {"id": "b", "name": "B"},
        ],
    }
    program = program_from_graph(graph)
    sol = solve_layout(program.model_copy(update={"boundary": (8.0, 6.0)}))
    out = apply_layout_to_graph(graph, sol)

    assert out["project_id"] == "p1"          # untouched
    assert out["style"] == {"primary": "Modern"}
    assert graph["spaces"][0] == {"id": "a", "name": "A", "prompt": "keep me"}  # original not mutated
    space_a = next(s for s in out["spaces"] if s["id"] == "a")
    assert space_a["prompt"] == "keep me"     # preserved
    assert "position" in space_a and "dimensions" in space_a
    assert space_a["dimensions"]["unit"] == "m"
    assert out["boundary"] == {"length": 8.0, "width": 6.0, "unit": "m"}
