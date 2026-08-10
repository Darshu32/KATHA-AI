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
    reconcile_program,
)

_RES = space_standards.RESIDENTIAL


def test_parse_bedrooms_from_common_phrasings():
    assert parse_bedrooms("3BHK apartment") == 3
    assert parse_bedrooms("a 2 BHK flat") == 2
    assert parse_bedrooms("4-bedroom villa") == 4
    assert parse_bedrooms("a modern house") is None
    # Bare "beds"/"br" are furniture/context, not a home program.
    assert parse_bedrooms("a room with 3 beds and a sofa") is None
    assert parse_bedrooms("4 br studio") is None


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


# ── Hybrid reconcile (the pipeline behaviour) ────────────────────────────────

def test_reconcile_rescues_a_collapsed_home():
    # The classic failure: the model collapsed a 3BHK into one room.
    collapsed = {"design_type": "interior", "spaces": [
        {"id": "s1", "name": "Apartment", "room_type": "living_room"}], "objects": [{"id": "x"}]}
    out = reconcile_program(collapsed, {"prompt": "3BHK apartment, 1100 sqft"})
    assert out is not None
    ids = {s["id"] for s in out["graph"]["spaces"]}
    assert {"master", "bed2", "bed3", "living", "kitchen", "bath1", "hall"} <= ids  # full program restored
    assert out["graph"]["objects"] == []  # cleared for re-furnishing


def test_reconcile_keeps_a_model_detected_study():
    llm = {"design_type": "interior", "spaces": [
        {"id": "study1", "name": "Study", "room_type": "study",
         "dimensions": {"length": 3, "width": 2.5}}]}
    out = reconcile_program(llm, {"prompt": "3BHK with a study, 1200 sqft"})
    names = {s["name"] for s in out["graph"]["spaces"]}
    assert "Study" in names                              # the special survived
    study = next(s for s in out["graph"]["spaces"] if s["name"] == "Study")
    assert study["area"] == 7.5                          # its stated 3×2.5 area was kept


def test_reconcile_is_a_no_op_without_a_bedroom_count():
    single = {"design_type": "interior", "spaces": [{"id": "r", "room_type": "living_room"}]}
    assert reconcile_program(single, {"prompt": "a modern living room"}) is None


def test_reconcile_keeps_a_full_llm_decomposition():
    # The model already produced the 3 bedrooms — don't replace its design.
    llm = {"design_type": "interior", "spaces": [
        {"id": "m", "room_type": "bedroom", "name": "Master"},
        {"id": "b2", "room_type": "bedroom"}, {"id": "b3", "room_type": "bedroom"},
        {"id": "l", "room_type": "living_room"}, {"id": "k", "room_type": "kitchen"}]}
    assert reconcile_program(llm, {"prompt": "3 bedroom penthouse, marble living room"}) is None
