"""Multi-room spatial model + resolver path (cascade stages A + B).

Additive only: the typed model gains ``RoomPlacement`` / ``SpatialModel.rooms``
and the resolver populates them from *placed* spaces, while the singular
``room`` and every other field stay exactly as before. These tests pin both the
new behaviour and the "single-room path is unchanged" guarantee.
"""

from __future__ import annotations

import pytest

from app.models.spatial_spec import RoomEnvelope, RoomPlacement, SpatialModel, Vec3
from app.services.layout_solver import (
    LayoutProgram,
    RoomSpec,
    apply_layout_to_graph,
    placements_from_solution,
    program_from_graph,
    solve_layout,
)
from app.services.spatial_resolver import resolve_spatial_model


# ── The typed model ───────────────────────────────────────────────────────


def test_room_placement_area_is_computed():
    rp = RoomPlacement(
        id="a", name="A", position=Vec3(x=1, y=0, z=2),
        envelope=RoomEnvelope(length=4, width=3, height=2.8),
    )
    assert rp.area == pytest.approx(12.0)


def test_spatial_model_rooms_defaults_empty():
    # A model built the old way (no rooms) is still valid — additive field.
    m = SpatialModel(kind="interior", room=RoomEnvelope(length=5, width=4, height=2.7))
    assert m.rooms == []


# ── Solution → typed placements ───────────────────────────────────────────


def test_placements_from_solution_maps_geometry_and_heights():
    program = LayoutProgram(
        rooms=[RoomSpec(id="a", area=12), RoomSpec(id="b", area=12)],
        boundary=(6.0, 4.0), seed=0,
    )
    sol = solve_layout(program)
    placements = placements_from_solution(sol, heights={"a": 3.0})

    assert {p.id for p in placements} == {"a", "b"}
    pa = next(p for p in placements if p.id == "a")
    pb = next(p for p in placements if p.id == "b")
    assert pa.envelope.height == 3.0      # supplied
    assert pb.envelope.height == 2.8      # default fallback

    sol_a = next(r for r in sol.rooms if r.id == "a")
    assert pa.position.x == pytest.approx(sol_a.x)
    assert pa.position.z == pytest.approx(sol_a.z)
    assert pa.envelope.length == pytest.approx(sol_a.length)
    assert pa.envelope.width == pytest.approx(sol_a.width)


# ── Resolver: single-room path is unchanged ───────────────────────────────


def test_single_unsolved_room_has_no_placements():
    # A room with dimensions but no position is the classic single-room graph:
    # ``room`` resolves as before, ``rooms`` stays empty.
    graph = {"spaces": [{"id": "only", "dimensions": {"length": 5, "width": 4, "height": 2.7, "unit": "m"}}]}
    model = resolve_spatial_model(graph)
    assert model.rooms == []
    assert model.kind == "interior"
    assert model.room is not None
    assert model.room.length == pytest.approx(5.0)
    assert len(model.walls) == 4  # perimeter walls still derived


# ── Resolver: multi-room graph ────────────────────────────────────────────


def test_placed_spaces_become_room_placements():
    graph = {
        "spaces": [
            {"id": "a", "name": "A", "position": {"x": 0, "y": 0, "z": 0},
             "dimensions": {"length": 4, "width": 3, "height": 2.8, "unit": "m"}},
            {"id": "b", "name": "B", "position": {"x": 4, "y": 0, "z": 0},
             "dimensions": {"length": 4, "width": 3, "height": 2.8, "unit": "m"}},
        ]
    }
    model = resolve_spatial_model(graph)
    assert len(model.rooms) == 2
    a = next(r for r in model.rooms if r.id == "a")
    b = next(r for r in model.rooms if r.id == "b")
    assert a.position.x == pytest.approx(0.0) and b.position.x == pytest.approx(4.0)
    assert a.envelope.length == pytest.approx(4.0) and a.area == pytest.approx(12.0)
    assert model.room is not None  # primary envelope still derived (stage C wires walls)


def test_spaces_without_position_are_skipped():
    # Mixed graph: one placed room, one bare. Only the placed one is a placement.
    graph = {
        "spaces": [
            {"id": "placed", "position": {"x": 0, "y": 0, "z": 0},
             "dimensions": {"length": 4, "width": 3, "height": 2.8, "unit": "m"}},
            {"id": "bare", "dimensions": {"length": 4, "width": 3}},
        ]
    }
    model = resolve_spatial_model(graph)
    assert [r.id for r in model.rooms] == ["placed"]


# ── End-to-end: solve → write back → resolve ──────────────────────────────


def test_solver_to_graph_to_resolver_roundtrip():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "area": 24},
            {"id": "kitchen", "name": "Kitchen", "area": 12},
            {"id": "bed", "name": "Bed", "area": 14},
        ]
    }
    program = program_from_graph(graph, seed=0)
    solution = solve_layout(program)
    placed_graph = apply_layout_to_graph(graph, solution)

    model = resolve_spatial_model(placed_graph)
    assert {r.id for r in model.rooms} == {"living", "kitchen", "bed"}
    # Areas survive the graph round-trip (mm-snap tolerance).
    targets = {"living": 24, "kitchen": 12, "bed": 14}
    for r in model.rooms:
        assert r.area == pytest.approx(targets[r.id], rel=1e-2)
