"""Multi-room program generation (cascade stage F).

The LLM contract now carries a `rooms` program + `adjacencies`. The LLM call
itself isn't unit-testable, but the deterministic half is: `_ai_response_to_design_graph`
must turn a multi-room `data` payload into multi-room `spaces` (+ adjacencies)
with no positions, survive the theme applier, and feed straight into the layout
solver seam — while a single-room payload stays exactly one space.
"""

from __future__ import annotations

from app.services.ai_orchestrator import (
    DESIGN_GRAPH_JSON_SCHEMA,
    _ai_response_to_design_graph,
)
from app.services.layout_solver import maybe_solve_layout
from app.services.parametric_theme_applier import apply_theme as apply_parametric_theme


def _multiroom_data():
    return {
        "room": {"type": "living_room", "dimensions": {"length": 6, "width": 4, "height": 2.8}},
        "rooms": [
            {"id": "living", "type": "living_room", "area_sqm": 24},
            {"id": "kitchen", "type": "kitchen", "area_sqm": 12},
            {"id": "master", "type": "bedroom", "area_sqm": 16},
            {"id": "bath", "type": "bathroom", "area_sqm": 5},
        ],
        "adjacencies": [{"a": "living", "b": "kitchen"}, {"a": "master", "b": "bath"}],
        "style": {"primary": "modern", "secondary": [], "color_palette": [], "materials": []},
        "objects": [], "materials": [], "lighting": [],
        "render_prompt_2d": "", "render_prompt_3d": "",
    }


# ── The strict schema exposes the program fields ──────────────────────────


def test_schema_requires_program_fields():
    props = DESIGN_GRAPH_JSON_SCHEMA["schema"]["properties"]
    req = DESIGN_GRAPH_JSON_SCHEMA["schema"]["required"]
    assert "rooms" in props and "adjacencies" in props
    # strict mode: every property must be required (empty arrays for single-room)
    assert "rooms" in req and "adjacencies" in req


# ── Multi-room payload → program spaces ───────────────────────────────────


def test_multiroom_payload_builds_program_spaces():
    g = _ai_response_to_design_graph(_multiroom_data(), "p1")
    assert len(g.spaces) == 4
    assert {s["id"] for s in g.spaces} == {"living", "kitchen", "master", "bath"}
    areas = {s["id"]: s["area"] for s in g.spaces}
    assert areas["living"] == 24 and areas["bath"] == 5
    assert len(g.adjacencies) == 2
    # rooms are unplaced — positioning is the solver's job, not the LLM's
    assert all("position" not in s for s in g.spaces)


def test_single_room_payload_stays_one_space():
    data = {**_multiroom_data(), "rooms": [], "adjacencies": []}
    g = _ai_response_to_design_graph(data, "p1")
    assert len(g.spaces) == 1
    assert g.spaces[0]["id"] == "space_001"
    assert g.adjacencies == []


# ── End-to-end: program → theme applier → solver seam ─────────────────────


def test_program_survives_theme_applier_and_solves():
    data = _multiroom_data()
    themed = apply_parametric_theme(data, "modern")["graph"]
    g = _ai_response_to_design_graph(themed, "p1")
    assert len(g.spaces) == 4          # rooms survived the parametric theme pass

    # the pipeline seam turns the program into a placed plan
    solved, solution = maybe_solve_layout(g.model_dump())
    assert solution is not None and len(solution.rooms) == 4
    for space in solved["spaces"]:
        assert "position" in space and "dimensions" in space
    # both requested adjacencies are satisfiable in a 4-room plan
    assert solution.adjacency_satisfaction >= 0.5
