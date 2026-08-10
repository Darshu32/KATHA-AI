"""The constraint → design-reasoning engine: climate becomes a design *driver*,
not just a checker. Deterministic, grounded in the NBC/SP 41 zone data.

The load-bearing test is `test_hot_west_facade_proposes_a_brise_soleil`: a hot
climate + a sun-exposed facade must PROPOSE shading — the system deciding a move
from the constraints, with no "louvre"/"slats" anywhere in the input.
"""
from __future__ import annotations

from app.services.design_reasoning import (
    apply_directives,
    derive_directives,
    reason,
    shade_directions,
    zone_for,
)
from app.knowledge import climate


def _cats(directives):
    return {d.category for d in directives}


# ── The flagship: climate proposes the move ──────────────────────────────────

def test_hot_west_facade_proposes_a_brise_soleil():
    directives = derive_directives({"climate_zone": "hot_dry", "facade_orientation": "west"})
    shading = [d for d in directives if d.category == "shading"]
    assert len(shading) == 1
    assert shading[0].target == "W"
    assert shading[0].params["device"] == "brise_soleil"
    # The rationale explains WHY, grounded in the zone knowledge.
    assert "hot" in shading[0].rationale.lower() and "sun" in shading[0].rationale.lower()


def test_shading_directive_injects_a_screen_on_the_front_facade():
    graph = {"design_type": "architecture", "objects": [
        {"id": "mass", "type": "building", "role": "massing", "material": "brick",
         "position": {"x": 0, "y": 0, "z": 0},
         "dimensions": {"length": 12, "width": 10, "height": 9}}]}
    out = reason(graph, {"climate_zone": "hot_dry", "facade_orientation": "west"})
    screens = [o for o in out["graph"]["objects"] if o.get("type") == "screen"]
    assert len(screens) == 1                      # a brise-soleil was added…
    assert screens[0]["position"]["z"] > 4.9      # …on the +z (front) facade
    assert screens[0]["gradient"] == "top"        # graded dense-at-top for high sun
    assert any("brise-soleil" in r.lower() or "shade" in r.lower() for r in out["rationale"])


# ── Cold climate does the opposite — no shading, admit the sun ───────────────

def test_cold_climate_does_not_shade_and_admits_south_sun():
    directives = derive_directives({"climate_zone": "cold", "facade_orientation": "south"})
    assert "shading" not in _cats(directives)     # never shade a heating-dominated facade
    solar = [d for d in directives if d.category == "solar_gain"]
    assert solar and solar[0].target == "S"

    graph = {"objects": [{"id": "m", "type": "building", "role": "massing",
                          "position": {"x": 0, "y": 0, "z": 0},
                          "dimensions": {"length": 10, "width": 8, "height": 6}}]}
    out = apply_directives(graph, directives)
    assert not [o for o in out["objects"] if o.get("type") == "screen"]  # nothing shaded


# ── Zone-specific reasoning ──────────────────────────────────────────────────

def test_warm_humid_requires_cross_ventilation():
    directives = derive_directives({"climate_zone": "warm_humid", "facade_orientation": "west"})
    assert "ventilation" in _cats(directives)


def test_glazing_cap_matches_the_zone_envelope_target():
    directives = derive_directives({"climate_zone": "hot_dry", "facade_orientation": "north"})
    cap = next(d for d in directives if d.category == "glazing")
    assert cap.params["window_wall_ratio_max"] == climate.get("hot_dry")["glazing"]["window_wall_ratio_max"]


def test_a_north_facade_in_a_hot_zone_is_not_shaded():
    # North gets no harsh sun — shading it would be wrong.
    directives = derive_directives({"climate_zone": "hot_dry", "facade_orientation": "north"})
    assert "shading" not in _cats(directives)
    assert "orientation" in _cats(directives)     # but orientation guidance still applies


def test_location_resolves_to_a_zone():
    assert zone_for({"location": "Chennai"}) == "warm_humid"
    assert zone_for({"location": "Jaipur"}) == "hot_dry"
    directives = derive_directives({"location": "Chennai", "facade_orientation": "west"})
    assert "shading" in _cats(directives)


def test_unknown_zone_yields_no_directives():
    assert derive_directives({"climate_zone": "martian", "facade_orientation": "west"}) == []


def test_shade_directions_are_grounded_in_zone_data():
    hot = climate.get("hot_dry")
    dirs = shade_directions("hot_dry", hot)
    assert "W" in dirs and "E" in dirs            # from minimise_openings "E, W"
    assert shade_directions("cold", climate.get("cold")) == set()
