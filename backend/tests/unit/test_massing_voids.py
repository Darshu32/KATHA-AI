"""Exterior massing: a `void`/`cutout` volume carves a real recess into a
grounded solid mass, instead of the boxes-only schema that dropped recesses
(loggias, undercuts, cantilever undersides) and left volumes floating on stilts.

The prompt (design_graph.py rule 14) now tells the LLM it may emit void volumes;
the kernel already subtracts them (kernel._VOID_TYPES). These tests guard the
kernel end of that contract through the real normalize + build_scene path.
"""
from __future__ import annotations

from app.services.graph_normalizer import normalize_graph
from app.services.spatial.kernel import _material_color, build_scene

_FULL_BOX = 12.0 * 10.0 * 9.0  # the mass before any carving


def _massing(*, with_void: bool) -> dict:
    objs = [{
        "id": "mass", "type": "building", "name": "Mass", "role": "massing",
        "material": "brick", "position": {"x": 0, "y": 0, "z": 0},
        "dimensions": {"length": 12, "width": 10, "height": 9},
    }]
    if with_void:
        objs.append({
            "id": "loggia", "type": "void", "name": "Loggia", "role": "massing",
            "position": {"x": 0, "y": 3.5, "z": 4},
            "dimensions": {"length": 8, "width": 4, "height": 5},
        })
    return {"design_type": "architecture", "style": {"primary": "modern"},
            "site": {"unit": "metric"}, "spaces": [], "objects": objs,
            "materials": [{"name": "brick"}]}


def _mass_solid(graph: dict):
    solids, _bbox, kind = build_scene(graph)
    assert kind == "exterior"
    mass = next((s for s in solids if s.id == "mass"), None)
    assert mass is not None, "the solid mass must be rendered"
    return mass, solids


def test_solid_only_mass_is_the_full_box_and_grounded():
    g, _ = normalize_graph(_massing(with_void=False))
    mass, _ = _mass_solid(g)
    assert abs(mass.manifold.volume() - _FULL_BOX) < 1.0
    assert abs(mass.manifold.bounding_box()[1]) < 0.01  # sits on the ground (y0 = 0)


def test_void_carves_a_real_recess_and_is_not_itself_rendered():
    g, _ = normalize_graph(_massing(with_void=True))
    mass, solids = _mass_solid(g)
    # The void overlaps the mass by 8×5×3 = 120 m³; that volume is removed.
    carved = _FULL_BOX - mass.manifold.volume()
    assert 100.0 <= carved <= 140.0, f"expected ~120 m³ carved, got {carved:.1f}"
    # A void is subtractive only — it must never appear as a solid box.
    assert "loggia" not in [s.id for s in solids]
    # The carved mass still sits on the ground — no floating.
    assert abs(mass.manifold.bounding_box()[1]) < 0.01


def test_cutout_is_accepted_as_a_void_alias():
    g_dict = _massing(with_void=True)
    g_dict["objects"][1]["type"] = "cutout"  # alias for "void"
    g, _ = normalize_graph(g_dict)
    mass, _ = _mass_solid(g)
    assert (_FULL_BOX - mass.manifold.volume()) > 100.0


# ── Screens / brise-soleil ───────────────────────────────────────────────────

def _screen(**overrides) -> dict:
    scr = {"id": "screen", "type": "screen", "role": "massing", "material": "timber",
           "orientation": "horizontal", "position": {"x": 0, "y": 3.5, "z": 4.9},
           "dimensions": {"length": 8, "width": 0.15, "height": 5}}
    scr.update(overrides)
    base = _massing(with_void=True)
    base["objects"].append(scr)
    return base


def _slats(graph: dict) -> list:
    solids, _bbox, _kind = build_scene(graph)
    return [s for s in solids if s.type == "screen"]


def test_screen_expands_into_many_thin_slats_not_one_box():
    g, _ = normalize_graph(_screen())
    slats = _slats(g)
    assert len(slats) >= 8, "a screen must render as an array of slats"
    for s in slats:  # each slat is thin in Y (a horizontal louvre)
        b = s.manifold.bounding_box()
        assert (b[4] - b[1]) < 0.2


def test_screen_slat_count_is_respected():
    g, _ = normalize_graph(_screen(slat_count=10))
    assert len(_slats(g)) == 10


def test_vertical_screen_stacks_across_x():
    g, _ = normalize_graph(_screen(orientation="vertical", slat_count=6))
    slats = _slats(g)
    assert len(slats) == 6
    for s in slats:  # thin in X, full height in Y
        b = s.manifold.bounding_box()
        assert (b[3] - b[0]) < 0.2 and (b[4] - b[1]) > 3.0


def test_material_color_resolves_descriptive_strings():
    brick = _material_color("pale cream-beige Roman brick")
    timber = _material_color("dark stained timber")
    assert brick is not None and timber is not None
    assert sum(brick) > sum(timber)                     # brick reads lighter than dark timber
    assert _material_color("pale brick")[0] > _material_color("brick")[0]   # "pale" lightens
    assert _material_color("dark timber")[0] < _material_color("timber")[0]  # "dark" darkens
    assert _material_color("unobtanium") is None        # unknown → falls through to type default


def test_massing_solids_take_their_material_colour():
    g, _ = normalize_graph({
        "design_type": "architecture", "site": {"unit": "metric"}, "spaces": [],
        "materials": [], "objects": [
            {"id": "mass", "type": "building", "role": "massing",
             "material": "pale cream-beige Roman brick",
             "position": {"x": 0, "y": 0, "z": 0},
             "dimensions": {"length": 12, "width": 10, "height": 9}}]})
    solids, _bbox, _kind = build_scene(g)
    mass = next(s for s in solids if s.id == "mass")
    # Not the grey clay default (0.86, 0.85, 0.82) — a warm brick tone instead.
    assert mass.color != (0.86, 0.85, 0.82)
    assert mass.color[0] > mass.color[2]  # warm: more red than blue


def test_gradient_biases_slat_spacing():
    # "top" gradient packs slats denser near the top than a uniform screen would.
    g, _ = normalize_graph(_screen(slat_count=12, gradient="top"))
    slats = _slats(g)
    ys = sorted((s.manifold.bounding_box()[1] for s in slats))  # slat base heights
    top_gap = ys[-1] - ys[-2]
    bottom_gap = ys[1] - ys[0]
    assert top_gap < bottom_gap, "top gradient should be tighter at the top"
