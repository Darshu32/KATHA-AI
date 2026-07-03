"""Tests for the deterministic perimeter-wall + opening derivation.

The wall model is the shared source of truth for "where are the walls and where
are the holes in them", consumed by both the SVG renderers and the IFC export.
These run the same normalized fixtures the other harnesses use, so a design that
breaks wall/opening derivation gets pinned here forever.
"""

from __future__ import annotations

import pytest

from app.services.graph_normalizer import normalize_graph
from app.services.wall_model import (
    WALL_THICKNESS_M,
    derive_wall_model,
    wall_by_side,
)
from tests.unit.test_graph_normalizer import ALL_FIXTURES


def _clean(name: str) -> dict:
    clean, _ = normalize_graph(ALL_FIXTURES[name]())
    return clean


def test_model_has_four_perimeter_walls() -> None:
    model = derive_wall_model(_clean("clean_kitchen"))
    sides = {w["side"] for w in model["walls"]}
    assert sides == {"south", "north", "west", "east"}
    assert model["thickness"] == WALL_THICKNESS_M


@pytest.mark.parametrize("name", list(ALL_FIXTURES))
def test_wall_lengths_match_room(name: str) -> None:
    clean = _clean(name)
    model = derive_wall_model(clean)
    L, W = model["room"]["length"], model["room"]["width"]
    assert wall_by_side(model, "south")["length"] == pytest.approx(L)
    assert wall_by_side(model, "north")["length"] == pytest.approx(L)
    assert wall_by_side(model, "west")["length"] == pytest.approx(W)
    assert wall_by_side(model, "east")["length"] == pytest.approx(W)


def test_window_becomes_a_real_opening_not_a_thin_box() -> None:
    """The living-room window is stored width=0.1, length=1.5 (mis-oriented).

    The wall model must read its along-wall extent as the *larger* horizontal
    dimension (~1.5 m), not the 0.1 m thickness — otherwise the window renders
    as a hairline.
    """
    clean = _clean("broken_axis_living_room")
    model = derive_wall_model(clean)
    openings = [o for w in model["walls"] for o in w["openings"]]
    win = next(o for o in openings if o["source_id"] == "win_1")
    assert win["kind"] == "window"
    assert win["width"] == pytest.approx(1.5, abs=0.05), "window opening should be ~1.5 m wide"
    assert win["width"] > 1.0  # emphatically not the 0.1 m thickness


def test_openings_sit_within_their_wall() -> None:
    for name in ALL_FIXTURES:
        model = derive_wall_model(_clean(name))
        for wall in model["walls"]:
            for op in wall["openings"]:
                assert op["center"] - op["width"] / 2 >= -1e-3
                assert op["center"] + op["width"] / 2 <= wall["length"] + 1e-3


def test_window_has_sill_door_reaches_floor() -> None:
    clean = _clean("broken_axis_living_room")
    model = derive_wall_model(clean)
    openings = {o["source_id"]: o for w in model["walls"] for o in w["openings"]}
    win = openings["win_1"]
    assert win["sill"] > 0.0          # windows sit off the floor
    assert win["head"] <= model["room"]["height"] + 1e-6


def test_opening_head_never_exceeds_ceiling() -> None:
    for name in ALL_FIXTURES:
        model = derive_wall_model(_clean(name))
        H = model["room"]["height"]
        for wall in model["walls"]:
            for op in wall["openings"]:
                assert op["head"] <= H + 1e-6
                assert op["sill"] < op["head"]


def test_deterministic() -> None:
    clean = _clean("broken_axis_living_room")
    assert derive_wall_model(clean) == derive_wall_model(clean)


def test_handles_empty_graph() -> None:
    model = derive_wall_model({})
    assert len(model["walls"]) == 4
    assert all(w["openings"] == [] for w in model["walls"])
