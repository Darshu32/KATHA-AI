"""Deterministic per-room furnishing (render-quality fold-in).

Each solved room gets room-appropriate furniture placed in world coordinates
inside its bounds, replacing the LLM's single-room-framed objects that would
otherwise land in the wrong rooms. Service rooms stay clear.
"""

from __future__ import annotations

from app.services.layout_solver import furnish_rooms, maybe_solve_layout
from app.services.layout_solver.furnish import _category


def _apartment():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living Room", "area": 22},
            {"id": "kitchen", "name": "Kitchen", "area": 10},
            {"id": "master", "name": "Master Bedroom", "area": 16},
            {"id": "bed2", "name": "Bedroom 2", "area": 12},
            {"id": "bath", "name": "Bathroom", "area": 4, "max_aspect": 2.6},
            {"id": "hall", "name": "Hall", "area": 6, "max_aspect": 4.0},
        ],
        "adjacencies": [["hall", "living"], ["hall", "kitchen"], ["hall", "master"],
                        ["hall", "bed2"], ["master", "bath"]],
        "objects": [], "materials": [],
    }
    solved, _ = maybe_solve_layout(graph)
    return solved


def _containing_room(obj, spaces):
    px, pz = obj["position"]["x"], obj["position"]["z"]
    for s in spaces:
        x0, z0 = s["position"]["x"], s["position"]["z"]
        L, W = s["dimensions"]["length"], s["dimensions"]["width"]
        if x0 - 0.02 <= px <= x0 + L + 0.02 and z0 - 0.02 <= pz <= z0 + W + 0.02:
            return s
    return None


# ── Classification ────────────────────────────────────────────────────────


def test_category_from_room_name():
    assert _category("Master Bedroom") == "bedroom"
    assert _category("Kitchen") == "kitchen"
    assert _category("Bathroom") == "bathroom"
    assert _category("Living Room") == "living"
    assert _category("Dining") == "dining"
    assert _category("Hall") == ""        # service → no furniture
    assert _category("Corridor") == ""


# ── Placement ─────────────────────────────────────────────────────────────


def test_rooms_get_type_appropriate_furniture():
    out = furnish_rooms(_apartment())
    types = {o["type"] for o in out["objects"]}
    assert {"sofa", "counter", "bed", "wc"} <= types      # living / kitchen / bedroom / bath


def test_every_piece_sits_fully_inside_its_room():
    out = furnish_rooms(_apartment())
    spaces = out["spaces"]
    for o in out["objects"]:
        room = _containing_room(o, spaces)
        assert room is not None, f"{o['type']} not in any room"
        px, pz = o["position"]["x"], o["position"]["z"]
        L, W = o["dimensions"]["length"], o["dimensions"]["width"]
        x0, z0 = room["position"]["x"], room["position"]["z"]
        rl, rw = room["dimensions"]["length"], room["dimensions"]["width"]
        assert x0 - 0.02 <= px - L / 2 and px + L / 2 <= x0 + rl + 0.02   # within on x
        assert z0 - 0.02 <= pz - W / 2 and pz + W / 2 <= z0 + rw + 0.02   # within on z
        assert o["position"]["y"] == 0.0 and o["role"] == "furniture"


def test_service_rooms_left_clear():
    out = furnish_rooms(_apartment())
    hall = next(s for s in out["spaces"] if s["id"] == "hall")
    for o in out["objects"]:
        r = _containing_room(o, out["spaces"])
        assert r is None or r["id"] != "hall"      # nothing placed in the hall


# ── Guardrails ────────────────────────────────────────────────────────────


def test_single_room_graph_is_untouched():
    graph = {"spaces": [{"id": "only", "position": {"x": 0, "y": 0, "z": 0},
                         "dimensions": {"length": 5, "width": 4}}]}
    assert furnish_rooms(graph) is graph          # <2 placed rooms → unchanged


def test_furniture_shrinks_to_fit_a_tiny_room():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "position": {"x": 0, "y": 0, "z": 0},
             "dimensions": {"length": 3, "width": 3}},
            {"id": "wc", "name": "WC", "position": {"x": 3, "y": 0, "z": 0},
             "dimensions": {"length": 1.2, "width": 1.0}},   # tiny
        ],
    }
    out = furnish_rooms(graph)
    for o in out["objects"]:
        if o["id"].startswith("wc"):
            assert o["dimensions"]["length"] <= 1.2 and o["dimensions"]["width"] <= 1.0
