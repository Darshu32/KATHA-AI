"""Unit tests for the pure geometry core (app/services/spatial/graph_geometry).

Structural assertions only — count things and check containment, never pixels.
The load-bearing test is that every object assign_objects() places has its centre
inside the room it was assigned to; that property is exactly what the spaces[0]
collapse violated.

Fixtures use the real authored conventions (confirmed against the kernel and the
live layout_solver/furnish.py): rooms and objects both map length→X, width→Z;
furniture dimensions come straight from the furnish.py catalogue.
"""
from __future__ import annotations

import pytest

from app.services.spatial.graph_geometry import (
    Rect,
    assign_objects,
    building_bbox,
    furnishable_objects,
    object_rect,
    object_rotation_y,
    placed_spaces,
    rect_contains_point,
    room_id,
    room_rect,
)


def _room(id_, name, x, z, length, width, height=2.9):
    return {"id": id_, "name": name, "room_type": name,
            "position": {"x": x, "z": z},
            "dimensions": {"length": length, "width": width, "height": height}}


def _obj(id_, type_, x, z, length, width, height=0.8, **extra):
    return {"id": id_, "type": type_, "name": type_, "role": "furniture",
            "position": {"x": x, "y": 0.0, "z": z},
            "dimensions": {"length": length, "width": width, "height": height}, **extra}


# LDK 6.0×4.5 + Bedroom 3.6×3.2 + Bathroom 3.6×1.3, tiling exactly to 9.6×4.5.
# Furniture dims are the real furnish.py values: sofa (2.1,0.9), bed (2.0,1.6), wc (0.6,0.5).
def _three_room():
    return {
        "design_type": "interior", "theme": "modern",
        "spaces": [
            _room("ldk", "Living Dining Kitchen", 0.0, 0.0, 6.0, 4.5),
            _room("bed1", "Bedroom", 6.0, 0.0, 3.6, 3.2),
            _room("bath1", "Bathroom", 6.0, 3.2, 3.6, 1.3),
        ],
        "objects": [
            _obj("sofa", "sofa", 3.0, 3.9, 2.1, 0.9),   # centre in LDK
            _obj("bed", "bed", 7.8, 1.6, 2.0, 1.6, 0.5),  # centre in Bedroom
            _obj("wc", "toilet", 6.5, 3.7, 0.6, 0.5, 0.4),  # centre in Bathroom
        ],
    }


def _single():
    return {"spaces": [_room("r1", "Studio", 0.0, 0.0, 4.0, 3.0)],
            "objects": [_obj("bed", "bed", 2.0, 1.5, 2.0, 1.6, 0.5)]}


def _two_gap():
    # Rooms do NOT touch: A occupies x 0–3, B occupies x 5–8. Gap 3–5.
    return {"spaces": [_room("a", "Room A", 0.0, 0.0, 3.0, 3.0),
                       _room("b", "Room B", 5.0, 0.0, 3.0, 3.0)],
            "objects": [_obj("desk_a", "desk", 1.5, 1.5, 1.6, 0.8),
                        _obj("desk_b", "desk", 6.5, 1.5, 1.6, 0.8)]}


# ── room_rect / object_rect maths ────────────────────────────────────────────

def test_room_rect_corner_origin():
    r = room_rect(_three_room()["spaces"][0])
    assert r == Rect(0.0, 6.0, 0.0, 4.5, 0.0, 2.9)


def test_three_rooms_tile_exactly():
    ldk, bed, bath = (room_rect(s) for s in _three_room()["spaces"])
    # bedroom and bathroom sit flush to the right of the LDK and stack in z.
    assert bed.x0 == pytest.approx(6.0) and bed.x1 == pytest.approx(9.6)
    assert bath.x0 == pytest.approx(6.0) and bath.x1 == pytest.approx(9.6)
    assert bed.z1 == pytest.approx(bath.z0)          # they share the z=3.2 wall
    assert bed.z1 == pytest.approx(3.2) and bath.z1 == pytest.approx(4.5)


def test_object_rect_is_centre_origin_length_x_width_z():
    # sofa centre (3.0, 3.9), length 2.1 along X, width 0.9 along Z.
    r = object_rect(_three_room()["objects"][0])
    assert r.x0 == pytest.approx(1.95) and r.x1 == pytest.approx(4.05)  # 3.0 ± 2.1/2
    assert r.z0 == pytest.approx(3.45) and r.z1 == pytest.approx(4.35)  # 3.9 ± 0.9/2


def test_object_rotation_y_tolerates_dict_and_list_and_absent():
    assert object_rotation_y(_obj("a", "bed", 0, 0, 2, 1, rotation={"y": 90})) == pytest.approx(90.0)
    assert object_rotation_y(_obj("a", "bed", 0, 0, 2, 1, rotation=[0, 45, 0])) == pytest.approx(45.0)
    assert object_rotation_y(_obj("a", "bed", 0, 0, 2, 1)) == 0.0


# ── placed_spaces / building_bbox ────────────────────────────────────────────

def test_placed_spaces_skips_unpositioned():
    g = _three_room()
    g["spaces"].append({"id": "ghost", "name": "No Position",
                        "dimensions": {"length": 3, "width": 3, "height": 2.7}})
    assert len(placed_spaces(g)) == 3           # the position-less room is skipped


def test_building_bbox_unions_all_rooms():
    assert building_bbox(_three_room()) == Rect(0.0, 9.6, 0.0, 4.5, 0.0, 2.9)


def test_building_bbox_none_when_empty():
    assert building_bbox({"spaces": []}) is None


def test_furnishable_excludes_structure_and_openings():
    g = _single()
    g["objects"].append(_obj("d1", "door", 2.0, 0.0, 0.9, 0.1))
    g["objects"].append(_obj("w1", "window", 0.0, 1.5, 1.2, 0.1))
    kinds = {o["type"] for o in furnishable_objects(g)}
    assert kinds == {"bed"}                     # door + window filtered out


# ── assign_objects — the load-bearing behaviour ──────────────────────────────

def test_assign_objects_three_rooms_no_orphans():
    g = _three_room()
    by_room, orphans = assign_objects(g)
    assert orphans == []
    assert [o["id"] for o in by_room["ldk"]] == ["sofa"]
    assert [o["id"] for o in by_room["bed1"]] == ["bed"]
    assert [o["id"] for o in by_room["bath1"]] == ["wc"]


def test_every_assigned_object_centre_is_inside_its_room():
    # The assertion that would have caught the original bug.
    g = _three_room()
    by_room, _ = assign_objects(g)
    rects = {room_id(s, i): room_rect(s) for i, s in enumerate(placed_spaces(g))}
    for rid, objs in by_room.items():
        for o in objs:
            r = object_rect(o)
            cx, cz = (r.x0 + r.x1) / 2, (r.z0 + r.z1) / 2
            assert rect_contains_point(rects[rid], cx, cz), f"{o['id']} centre not in {rid}"


def test_assign_objects_disjoint_rooms():
    by_room, orphans = assign_objects(_two_gap())
    assert orphans == []
    assert [o["id"] for o in by_room["a"]] == ["desk_a"]
    assert [o["id"] for o in by_room["b"]] == ["desk_b"]


def test_room_with_zero_objects_present_and_empty():
    g = _single()
    g["objects"] = []
    by_room, orphans = assign_objects(g)
    assert by_room == {"r1": []} and orphans == []


def test_orphan_object_is_reported_not_dropped():
    g = _single()
    g["objects"] = [_obj("stray", "chair", 10.0, 10.0, 0.5, 0.5)]  # centre far outside
    by_room, orphans = assign_objects(g)
    assert [o["id"] for o in orphans] == ["stray"]
    assert by_room == {"r1": []}                # not silently swallowed into r1


def test_shared_wall_point_resolves_to_exactly_one_room():
    # A centre exactly on the x=6.0 wall shared by LDK (x1=6) and Bedroom (x0=6)
    # must land in the Bedroom (half-open high edge), never both.
    g = _three_room()
    g["objects"] = [_obj("edge", "chair", 6.0, 1.0, 0.5, 0.5)]
    by_room, orphans = assign_objects(g)
    assert orphans == []
    assert [o["id"] for o in by_room["bed1"]] == ["edge"]
    assert by_room["ldk"] == []
