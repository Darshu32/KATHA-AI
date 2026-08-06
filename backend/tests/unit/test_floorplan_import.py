"""Floor-plan → rooms (Layer 5B, upload → geometry).

The vision extraction needs a network model, but the deterministic half — a
room PROGRAM → a solved, furnished multi-room graph via the SAME builder +
layout solver the text-prompt path uses — is fully unit-testable.
"""

from __future__ import annotations

from app.services.floorplan_import import build_multiroom_graph


def _program() -> dict:
    return {
        "rooms": [
            {"id": "living", "type": "living_room", "area_sqm": 22},
            {"id": "kitchen", "type": "kitchen", "area_sqm": 11},
            {"id": "hall", "type": "hall", "area_sqm": 8},
            {"id": "bed1", "type": "bedroom", "area_sqm": 12},
            {"id": "bath", "type": "bathroom", "area_sqm": 4},
        ],
        "adjacencies": [
            {"a": "living", "b": "hall"}, {"a": "hall", "b": "bed1"},
            {"a": "hall", "b": "bath"}, {"a": "living", "b": "kitchen"},
        ],
        "notes": "",
    }


def test_program_builds_solved_furnished_multiroom_graph():
    graph, solution = build_multiroom_graph(_program(), "p1", "modern")
    assert solution is not None                       # the solver placed the program
    spaces = graph["spaces"]
    assert len(spaces) == 5
    for s in spaces:                                  # every room positioned + sized
        assert "position" in s and "dimensions" in s
    assert len(graph.get("objects") or []) > 0        # furnished


def test_dedup_ids_and_bad_area_are_defensive():
    prog = {
        "rooms": [
            {"id": "a", "type": "living_room", "area_sqm": 20},
            {"id": "a", "type": "kitchen", "area_sqm": 10},   # duplicate id → dropped
            {"id": "b", "type": "bedroom", "area_sqm": 0},    # 0 area → defaulted
        ],
        "adjacencies": [{"a": "a", "b": "b"}],
        "notes": "",
    }
    graph, solution = build_multiroom_graph(prog, "p2", None)
    ids = [s["id"] for s in graph["spaces"]]
    assert ids == ["a", "b"]                           # dup dropped, both survive
    assert solution is not None
