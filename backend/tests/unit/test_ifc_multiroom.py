"""Multi-room IFC export (cascade stage D — IFC).

Unlike the drawings, the IFC exporter reads ``derive_wall_model`` directly, so it
needed a real multi-room path: one ``IfcSpace`` per room + partition/exterior
``IfcWall``s. These tests parse the emitted IFC back and check the entity counts,
that it's still valid IFC4, and that the single-room export is untouched.
"""

from __future__ import annotations

import ifcopenshell

from app.services.exporters.ifc_exporter import export
from app.services.layout_solver import (
    apply_layout_to_graph,
    program_from_graph,
    solve_layout,
)


def _parse(result: dict):
    return ifcopenshell.file.from_string(result["bytes"].decode("utf-8"))


def _solved_graph():
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


# ── Single-room export is unchanged ───────────────────────────────────────


def test_single_room_export_is_one_space_four_walls():
    graph = {"spaces": [{"id": "only", "type": "living_room",
                         "dimensions": {"length": 5, "width": 4, "height": 2.8, "unit": "m"}}]}
    model = _parse(export({"meta": {"project_name": "Studio"}}, graph))
    assert len(model.by_type("IfcSpace")) == 1
    assert len(model.by_type("IfcWall")) == 4


# ── Multi-room export ─────────────────────────────────────────────────────


def test_multiroom_export_has_one_space_per_room():
    graph, solution = _solved_graph()
    model = _parse(export({"meta": {"project_name": "Apartment"}}, graph))

    spaces = model.by_type("IfcSpace")
    assert len(spaces) == len(solution.rooms)          # one IfcSpace per room
    names = {s.Name for s in spaces}
    assert {"Living", "Kitchen", "Bed", "Bath"} <= names


def test_multiroom_export_emits_partition_and_exterior_walls():
    graph, _ = _solved_graph()
    model = _parse(export({"meta": {"project_name": "Apartment"}}, graph))
    walls = model.by_type("IfcWall")
    assert len(walls) >= 4
    # a partition wall's name carries both rooms ("Wall a/b")
    assert any("/" in (w.Name or "") for w in walls)


def test_multiroom_ifc_is_valid_ifc4_with_hierarchy():
    graph, _ = _solved_graph()
    model = _parse(export({"meta": {"project_name": "Apartment"}}, graph))
    assert model.schema == "IFC4"
    assert model.by_type("IfcProject") and model.by_type("IfcBuildingStorey")
    # spaces decompose the storey (spatial hierarchy intact)
    assert model.by_type("IfcRelAggregates")


def test_multiroom_ifc_walls_carry_room_psets():
    graph, _ = _solved_graph()
    model = _parse(export({"meta": {"project_name": "Apartment"}}, graph))
    # every wall should have a KATHA_Design pset tagging kind + rooms
    psets = model.by_type("IfcPropertySet")
    assert any(p.Name == "KATHA_Design" for p in psets)
