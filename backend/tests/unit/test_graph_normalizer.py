"""Multi-design harness for the graph normalization + validation layer.

These fixtures stand in for "the next design the user generates". Any new
design that breaks a renderer should be added here as a fixture: the harness
reproduces it deterministically, you fix the *normalizer*, and the regression
is guarded forever after. The invariant checks are renderer-agnostic — they
assert the canonical contract every downstream consumer relies on.
"""

from __future__ import annotations

import copy

import pytest

from app.services.graph_normalizer import normalize_graph, validate_graph


# ── Fixtures: diverse, deliberately-flawed and already-clean designs ─────────


def _broken_axis_living_room() -> dict:
    """The real bedroom/living-room defect: depth in y, z pinned to 0."""
    return {
        "site": {"unit": "metric"},
        "style": {"primary": "Warm Contemporary"},
        "spaces": [{"id": "space_001", "name": "Living Room",
                    "dimensions": {"length": 5.49, "width": 4.27, "height": 2.75}}],
        "objects": [
            {"id": "sofa_1", "type": "sofa", "name": "Sofa",
             "position": {"x": 1.2, "y": 0.5, "z": 0.0},
             "dimensions": {"length": 2.0, "width": 0.9, "height": 0.8}},
            {"id": "table_1", "type": "coffee_table", "name": "Coffee Table",
             "position": {"x": 1.5, "y": 2.0, "z": 0.0},
             "dimensions": {"length": 1.1, "width": 0.6, "height": 0.4}},
            {"id": "win_1", "type": "window", "name": "Window",
             "position": {"x": 4.27, "y": 0.0, "z": 0.0},
             "dimensions": {"length": 1.5, "width": 0.1, "height": 1.2}},
            {"id": "plant_1", "type": "plant", "name": "Plant",
             "position": {"x": 4.0, "y": 0.5, "z": 0.0},
             "dimensions": {"length": 0.5, "width": 0.5, "height": 1.4}},
        ],
        "lighting": [],
    }


def _imperial_office() -> dict:
    """Values authored in feet with site.unit imperial — must become metres."""
    return {
        "site": {"unit": "imperial"},
        "style": {"primary": "Minimal"},
        "spaces": [{"id": "s1", "name": "Office",
                    "dimensions": {"length": 16.0, "width": 12.0, "height": 9.0}}],
        "objects": [
            {"id": "desk_1", "type": "desk", "name": "Desk",
             "position": {"x": 4.0, "y": 0.0, "z": 3.0},
             "dimensions": {"length": 4.0, "width": 2.0, "height": 2.5}},
            {"id": "chair_1", "type": "chair", "name": "Chair",
             "position": {"x": 4.0, "y": 0.0, "z": 5.0},
             "dimensions": {"length": 2.0, "width": 2.0, "height": 3.0}},
        ],
        "lighting": [],
    }


def _oversized_bedroom() -> dict:
    """A wardrobe larger than half the room + an object outside the walls."""
    return {
        "site": {"unit": "metric"},
        "style": {"primary": "Scandi"},
        "spaces": [{"id": "s1", "name": "Bedroom",
                    "dimensions": {"length": 4.0, "width": 3.0, "height": 2.7}}],
        "objects": [
            {"id": "bed_1", "type": "bed", "name": "Bed",
             "position": {"x": 2.0, "y": 0.0, "z": 1.5},
             "dimensions": {"length": 2.0, "width": 1.6, "height": 0.6}},
            {"id": "wardrobe_1", "type": "wardrobe", "name": "Wardrobe",
             "position": {"x": 3.8, "y": 0.0, "z": 2.8},
             "dimensions": {"length": 3.6, "width": 3.0, "height": 2.4}},  # too big
        ],
        "lighting": [],
    }


def _clean_kitchen() -> dict:
    """Already canonical: depth on z, metric units, fits the room."""
    return {
        "site": {"unit": "metric"},
        "style": {"primary": "Industrial"},
        "spaces": [{"id": "s1", "name": "Kitchen",
                    "dimensions": {"length": 5.0, "width": 4.0, "height": 2.8, "unit": "m"}}],
        "objects": [
            {"id": "counter_1", "type": "counter", "name": "Counter", "role": "furniture",
             "position": {"x": 1.0, "y": 0.0, "z": 0.5},
             "dimensions": {"length": 2.4, "width": 0.6, "height": 0.9, "unit": "m"}},
            {"id": "island_1", "type": "island", "name": "Island", "role": "furniture",
             "position": {"x": 2.5, "y": 0.0, "z": 2.0},
             "dimensions": {"length": 1.8, "width": 1.0, "height": 0.9, "unit": "m"}},
            {"id": "fridge_1", "type": "fridge", "name": "Fridge", "role": "furniture",
             "position": {"x": 4.5, "y": 0.0, "z": 3.5},
             "dimensions": {"length": 0.7, "width": 0.7, "height": 1.8, "unit": "m"}},
        ],
        "lighting": [],
    }


ALL_FIXTURES = {
    "broken_axis_living_room": _broken_axis_living_room,
    "imperial_office": _imperial_office,
    "oversized_bedroom": _oversized_bedroom,
    "clean_kitchen": _clean_kitchen,
}


# ── Renderer-agnostic invariant: holds for EVERY design after normalize ──────


@pytest.mark.parametrize("name", list(ALL_FIXTURES))
def test_every_design_is_clean_after_normalization(name: str) -> None:
    clean, report = normalize_graph(ALL_FIXTURES[name]())
    assert report["ok"], f"{name} still invalid: {report['errors']}"
    assert validate_graph(clean)["ok"]


@pytest.mark.parametrize("name", list(ALL_FIXTURES))
def test_units_are_metric_and_stamped(name: str) -> None:
    clean, _ = normalize_graph(ALL_FIXTURES[name]())
    assert clean["site"]["unit"] == "metric"
    for obj in clean["objects"]:
        assert obj["dimensions"]["unit"] == "m"


@pytest.mark.parametrize("name", list(ALL_FIXTURES))
def test_objects_stay_inside_room(name: str) -> None:
    clean, _ = normalize_graph(ALL_FIXTURES[name]())
    dims = clean["spaces"][0]["dimensions"]
    room_l, room_w = dims["length"], dims["width"]
    for obj in clean["objects"]:
        # Edge elements (walls/windows/doors) sit on the boundary by design.
        if obj.get("role") in {"wall", "window", "door"}:
            continue
        p, d = obj["position"], obj["dimensions"]
        assert p["x"] - d["width"] / 2 >= -1e-3
        assert p["x"] + d["width"] / 2 <= room_l + 1e-3
        assert p["z"] - d["length"] / 2 >= -1e-3
        assert p["z"] + d["length"] / 2 <= room_w + 1e-3


@pytest.mark.parametrize("name", list(ALL_FIXTURES))
def test_every_object_has_a_role(name: str) -> None:
    clean, _ = normalize_graph(ALL_FIXTURES[name]())
    for obj in clean["objects"]:
        assert obj.get("role"), f"{obj.get('id')} missing role"


# ── Targeted behaviour per root cause ────────────────────────────────────────


def test_axis_collapse_is_corrected() -> None:
    """Depth must move onto z; the design must regain real depth spread."""
    clean, report = normalize_graph(_broken_axis_living_room())
    zs = [o["position"]["z"] for o in clean["objects"]]
    assert max(zs) - min(zs) >= 1.0, "depth still collapsed after normalization"
    assert any(c["type"] == "axis" for c in report["corrections"])


def test_imperial_is_converted_to_metres() -> None:
    clean, report = normalize_graph(_imperial_office())
    # 16 ft ~= 4.877 m
    assert abs(clean["spaces"][0]["dimensions"]["length"] - 16 * 0.3048) < 1e-2
    assert any(c["type"] == "unit" for c in report["corrections"])


def test_oversized_object_is_scaled_to_fit() -> None:
    clean, _ = normalize_graph(_oversized_bedroom())
    room = clean["spaces"][0]["dimensions"]
    room_area = room["length"] * room["width"]
    wardrobe = next(o for o in clean["objects"] if o["id"] == "wardrobe_1")
    footprint = wardrobe["dimensions"]["width"] * wardrobe["dimensions"]["length"]
    assert footprint <= room_area * 0.6 + 1e-3


def test_edge_elements_snap_to_a_wall() -> None:
    clean, _ = normalize_graph(_broken_axis_living_room())
    room = clean["spaces"][0]["dimensions"]
    win = next(o for o in clean["objects"] if o["id"] == "win_1")
    assert win["role"] == "window"
    on_x_edge = win["position"]["x"] in (0.0, round(room["length"], 4))
    on_z_edge = win["position"]["z"] in (0.0, round(room["width"], 4))
    assert on_x_edge or on_z_edge


# ── Idempotency + safety ─────────────────────────────────────────────────────


def test_normalization_is_idempotent() -> None:
    once, _ = normalize_graph(_broken_axis_living_room())
    twice, report2 = normalize_graph(once)
    assert once == twice
    # Second pass should find nothing structural to correct.
    assert not any(c["type"] in ("axis", "unit") for c in report2["corrections"])


def test_clean_graph_is_untouched_structurally() -> None:
    clean, report = normalize_graph(_clean_kitchen())
    assert not any(c["type"] in ("axis", "unit") for c in report["corrections"])
    # z-depth spread preserved (no spurious axis swap).
    zs = [o["position"]["z"] for o in clean["objects"]]
    assert max(zs) - min(zs) > 1.0


def test_input_is_not_mutated() -> None:
    raw = _broken_axis_living_room()
    snapshot = copy.deepcopy(raw)
    normalize_graph(raw)
    assert raw == snapshot, "normalize_graph mutated its input"


def test_handles_garbage_input() -> None:
    clean, report = normalize_graph({"objects": "not a list", "spaces": None})
    assert "ok" in report  # does not raise
