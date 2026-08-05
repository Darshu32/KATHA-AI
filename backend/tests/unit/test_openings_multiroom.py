"""Openings on multi-room walls (fold-in).

Doors come from the adjacency graph — one per connected pair, in the partition
they share. Windows go on long-enough exterior walls. Then the kernel cuts them
as Manifold voids and IFC emits IfcOpeningElement + IfcDoor/IfcWindow.
"""

from __future__ import annotations

import ifcopenshell

from app.services.exporters.ifc_exporter import export
from app.services.layout_solver import maybe_solve_layout
from app.services.spatial.kernel import build_scene
from app.services.spatial_resolver import resolve_spatial_model
from app.services.wall_model import derive_multiroom_wall_model


def _two_rooms():
    return [
        {"id": "a", "x": 0, "z": 0, "length": 4, "width": 3, "height": 2.8},
        {"id": "b", "x": 4, "z": 0, "length": 4, "width": 3, "height": 2.8},
    ]


def _openings(segs, kind):
    return [op for s in segs for op in s["openings"] if op["kind"] == kind]


# ── Door placement from adjacencies ───────────────────────────────────────


def test_door_in_partition_between_adjacent_rooms():
    segs = derive_multiroom_wall_model(_two_rooms(), [["a", "b"]])
    doors = _openings(segs, "door")
    assert len(doors) == 1
    door_seg = next(s for s in segs if any(op["kind"] == "door" for op in s["openings"]))
    assert door_seg["kind"] == "partition"
    assert set(door_seg["rooms"]) == {"a", "b"}
    # door sits at the base of the wall (sill 0) and within its height
    assert doors[0]["sill"] == 0.0 and doors[0]["head"] <= 2.8


def test_no_door_without_an_adjacency():
    segs = derive_multiroom_wall_model(_two_rooms(), adjacencies=[])
    assert _openings(segs, "door") == []


def test_one_door_per_pair_even_with_split_partition():
    # A tall room A backs two stacked rooms B (lower) and C (upper): A-B and A-C.
    rooms = [
        {"id": "a", "x": 0, "z": 0, "length": 4, "width": 6, "height": 2.8},
        {"id": "b", "x": 4, "z": 0, "length": 4, "width": 3, "height": 2.8},
        {"id": "c", "x": 4, "z": 3, "length": 4, "width": 3, "height": 2.8},
    ]
    doors = _openings(derive_multiroom_wall_model(rooms, [["a", "b"], ["a", "c"]]), "door")
    assert len(doors) == 2  # one per adjacency pair


# ── Windows on exterior walls ─────────────────────────────────────────────


def test_windows_only_on_exterior_walls():
    segs = derive_multiroom_wall_model(_two_rooms(), [["a", "b"]])
    assert len(_openings(segs, "window")) >= 1
    for s in segs:
        for op in s["openings"]:
            if op["kind"] == "window":
                assert s["kind"] == "exterior"
                assert op["sill"] > 0.0  # windows sit above the floor


# ── Kernel cuts the voids ─────────────────────────────────────────────────


def test_kernel_walls_survive_void_cuts():
    g = {"spaces": [{"id": "a", "area": 16}, {"id": "b", "area": 16}, {"id": "c", "area": 12}],
         "adjacencies": [["a", "b"], ["b", "c"]]}
    solved, _ = maybe_solve_layout(g)
    solids, _bbox, _kind = build_scene(solved)
    walls = [s for s in solids if s.type == "wall"]
    assert walls
    for s in walls:                       # voids didn't destroy the meshes
        assert s.verts is not None and len(s.verts) > 0
        assert s.tris is not None and len(s.tris) > 0


# ── IFC emits doors / windows / openings ──────────────────────────────────


def test_ifc_emits_doors_windows_and_opening_voids():
    g = {"spaces": [{"id": "living", "name": "Living", "area": 24},
                    {"id": "kitchen", "name": "Kitchen", "area": 12},
                    {"id": "bed", "name": "Bed", "area": 14}],
         "adjacencies": [["living", "kitchen"], ["living", "bed"]]}
    solved, _ = maybe_solve_layout(g)
    model = ifcopenshell.file.from_string(
        export({"meta": {"project_name": "Apt"}}, solved)["bytes"].decode("utf-8")
    )
    assert len(model.by_type("IfcDoor")) >= 2       # living-kitchen, living-bed
    assert len(model.by_type("IfcWindow")) >= 1
    assert model.by_type("IfcOpeningElement")        # real voids, not floating boxes
    assert model.by_type("IfcRelVoidsElement") and model.by_type("IfcRelFillsElement")


# ── Resolver surfaces openings on the typed segments ──────────────────────


def test_resolver_wall_segments_carry_openings():
    g = {"spaces": [{"id": "a", "name": "A", "area": 16}, {"id": "b", "name": "B", "area": 16}],
         "adjacencies": [["a", "b"]]}
    solved, _ = maybe_solve_layout(g)
    sm = resolve_spatial_model(solved)
    ops = [op for w in sm.wall_segments for op in w.openings]
    assert any(op.kind == "door" for op in ops)
    assert any(op.kind == "window" for op in ops)
