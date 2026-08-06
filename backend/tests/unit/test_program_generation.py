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


def test_massing_payload_builds_architecture_graph():
    data = {
        "room": {"type": "building", "dimensions": {"length": 10, "width": 8, "height": 6}},
        "rooms": [], "adjacencies": [],
        "massing": [
            {"id": "gf", "type": "building", "position": {"x": 0, "y": 0, "z": 0},
             "dimensions": {"length": 10, "width": 8, "height": 3}, "material": "concrete"},
            {"id": "uf", "type": "block", "position": {"x": 0, "y": 3, "z": 0},
             "dimensions": {"length": 8, "width": 6, "height": 3}, "material": "glass"},
        ],
        "style": {"primary": "modern", "secondary": [], "color_palette": [], "materials": []},
        "objects": [], "materials": [], "lighting": [],
        "render_prompt_2d": "", "render_prompt_3d": "",
    }
    g = _ai_response_to_design_graph(data, "p1")
    assert g.design_type == "architecture"
    assert g.spaces == []                      # exterior: no interior rooms
    assert [o["id"] for o in g.objects] == ["gf", "uf"]
    assert all(o["role"] == "massing" for o in g.objects)


def test_massing_graph_renders_via_exterior_path():
    from app.services.spatial.kernel import build_scene
    graph = {
        "design_type": "architecture", "spaces": [],
        "objects": [
            {"id": "gf", "type": "building", "position": {"x": 0, "y": 0, "z": 0},
             "dimensions": {"length": 10, "width": 8, "height": 3}},
            {"id": "uf", "type": "block", "position": {"x": 0, "y": 3, "z": 0},
             "dimensions": {"length": 8, "width": 6, "height": 3}},
        ],
        "materials": [],
    }
    solids, _bbox, kind = build_scene(graph)
    assert kind == "exterior"                  # design_type routes to massing path
    uf = next(s for s in solids if s.id == "uf")
    assert uf.verts[:, 1].min() > 2.0          # upper floor kept its height (not floored)


def test_product_payload_builds_product_graph():
    data = {
        "room": {"type": "chair", "dimensions": {"length": 0.6, "width": 0.6, "height": 0.9}},
        "rooms": [], "adjacencies": [], "massing": [],
        "product": {"type": "lounge_chair", "parts": [
            {"id": "seat", "type": "seat", "position": {"x": 0, "y": 0.4, "z": 0},
             "dimensions": {"length": 0.6, "width": 0.6, "height": 0.12}, "material": "walnut"},
            {"id": "leg1", "type": "leg", "position": {"x": 0.25, "y": 0, "z": 0.25},
             "dimensions": {"length": 0.05, "width": 0.05, "height": 0.4}, "material": "walnut"},
        ]},
        "style": {"primary": "modern", "secondary": [], "color_palette": [], "materials": []},
        "objects": [], "materials": [], "lighting": [],
        "render_prompt_2d": "", "render_prompt_3d": "",
    }
    g = _ai_response_to_design_graph(data, "p1")
    assert g.design_type == "product"
    assert g.spaces == []
    assert [o["id"] for o in g.objects] == ["seat", "leg1"]
    assert all(o["role"] == "product_part" for o in g.objects)


def test_product_graph_renders_via_product_path():
    from app.services.spatial.kernel import build_scene
    graph = {
        "design_type": "product", "spaces": [],
        "objects": [
            {"id": "seat", "type": "seat", "position": {"x": 0, "y": 0.4, "z": 0},
             "dimensions": {"length": 0.6, "width": 0.6, "height": 0.12}},
            {"id": "leg", "type": "leg", "position": {"x": 0.25, "y": 0, "z": 0.25},
             "dimensions": {"length": 0.05, "width": 0.05, "height": 0.4}},
        ],
        "materials": [],
    }
    solids, _bbox, kind = build_scene(graph)
    assert kind == "product"
    seat = next(s for s in solids if s.id == "seat")
    assert seat.verts[:, 1].min() > 0.3            # seat kept its height (not floored)


def test_product_finish_prompt_is_studio_shot():
    from app.services.spatial.finish import build_finish_prompt
    p = build_finish_prompt({"design_type": "product", "style": {"primary": "modern"},
                             "objects": [{"material": "walnut"}]}, kind="product")
    assert "product" in p.lower()
    assert "studio" in p.lower() or "neutral background" in p.lower()


async def test_controlnet_depth_dormant_without_config():
    # The depth-ControlNet finish lock activates only when replicate_api_token +
    # controlnet_depth_model are set; unconfigured it returns None so the finish
    # falls back to the img2img providers (never breaks the pipeline).
    from app.services.spatial.finish import _controlnet_depth
    assert await _controlnet_depth(b"clay-bytes", b"depth-bytes", "photoreal render") is None


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
