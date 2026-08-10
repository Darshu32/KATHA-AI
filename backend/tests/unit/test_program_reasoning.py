"""Program → room-program reasoning: '3BHK' → a grounded room program the layout
solver can place. Deterministic, standards-backed (space_standards / NBC minima).

The load-bearing test is that the derived program flows straight into the layout
solver and every room gets placed — constraints → program → real floor plan.
"""
from __future__ import annotations

from app.knowledge import space_standards
from app.services.layout_solver import maybe_solve_layout
from app.services.program_reasoning import (
    derive_room_program,
    parse_area_sqm,
    parse_bedrooms,
    program_rationale,
)

_RES = space_standards.RESIDENTIAL


def test_parse_bedrooms_from_common_phrasings():
    assert parse_bedrooms("3BHK apartment") == 3
    assert parse_bedrooms("a 2 BHK flat") == 2
    assert parse_bedrooms("4-bedroom villa") == 4
    assert parse_bedrooms("a modern house") is None


def test_parse_area_sqft_and_sqm():
    assert parse_area_sqm({"built_up_area_sqm": 110}) == 110
    assert round(parse_area_sqm({"prompt": "3BHK, 1100 sqft"})) == round(1100 * 0.092903)


def test_3bhk_program_has_the_expected_rooms():
    prog = derive_room_program({"program": "3BHK", "built_up_area_sqm": 110})
    ids = {s["id"] for s in prog["spaces"]}
    # 3 bedrooms + living + kitchen + dining + 2 baths + hall
    assert {"master", "bed2", "bed3", "living", "kitchen", "dining", "bath1", "bath2", "hall"} == ids
    assert prog["program_summary"]["bedrooms"] == 3
    assert prog["program_summary"]["bathrooms"] == 2


def test_1bhk_is_leaner_no_dining_one_bath():
    prog = derive_room_program({"program": "1BHK"})
    ids = {s["id"] for s in prog["spaces"]}
    assert "dining" not in ids and "bath2" not in ids
    assert {"master", "living", "kitchen", "bath1", "hall"} == ids


def test_every_room_meets_its_nbc_minimum_area():
    prog = derive_room_program({"program": "2BHK", "built_up_area_sqm": 55})  # tight, forces clamping
    for s in prog["spaces"]:
        floor = _RES.get(s["room_type"], {}).get("min_area_m2", 0)
        assert s["area"] >= floor, f"{s['id']} {s['area']} < NBC min {floor}"


def test_areas_scale_with_built_up_and_master_is_largest_bedroom():
    small = derive_room_program({"program": "3BHK", "built_up_area_sqm": 90})
    big = derive_room_program({"program": "3BHK", "built_up_area_sqm": 160})
    a_small = next(s["area"] for s in small["spaces"] if s["id"] == "living")
    a_big = next(s["area"] for s in big["spaces"] if s["id"] == "living")
    assert a_big > a_small  # a bigger built-up gives bigger rooms
    beds = {s["id"]: s["area"] for s in big["spaces"] if s["room_type"] == "bedroom"}
    assert beds["master"] > beds["bed2"]  # master is the largest bedroom


def test_adjacencies_wire_through_the_hall_and_ensuite_master():
    prog = derive_room_program({"program": "3BHK", "built_up_area_sqm": 110})
    pairs = {frozenset((a["a"], a["b"])) for a in prog["adjacencies"]}
    assert frozenset(("hall", "living")) in pairs
    assert frozenset(("hall", "master")) in pairs
    assert frozenset(("master", "bath1")) in pairs  # en-suite


def test_program_flows_into_the_layout_solver_and_every_room_is_placed():
    prog = derive_room_program({"program": "3BHK", "built_up_area_sqm": 110})
    graph = {"design_type": "interior", "spaces": prog["spaces"], "adjacencies": prog["adjacencies"]}
    solved, solution = maybe_solve_layout(graph)
    assert solution is not None                        # a multi-room program was solved
    placed = [s for s in solved["spaces"] if isinstance(s.get("position"), dict)]
    assert len(placed) == len(prog["spaces"])          # EVERY room got a position


def test_rationale_explains_the_decomposition():
    lines = program_rationale(derive_room_program({"program": "3BHK", "built_up_area_sqm": 110}))
    assert lines and "3BHK" in lines[0] and "bedroom" in lines[0].lower()
