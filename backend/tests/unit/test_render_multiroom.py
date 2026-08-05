"""Multi-room render framing (render-quality fold-in).

Two things the render pipeline must get right for a multi-room plan: it is worth
rendering even before it's furnished (the rooms are the subject), and it frames
the WHOLE plan as a dollhouse rather than the single-room ``interior_camera``
cropped to ``spaces[0]``.
"""

from __future__ import annotations

from app.services.layout_solver import maybe_solve_layout
from app.services.spatial.kernel import build_scene
from app.services.spatial.render_pipeline import _build_and_raster


def _apartment():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "area": 24},
            {"id": "kitchen", "name": "Kitchen", "area": 12},
            {"id": "master", "name": "Master", "area": 16},
            {"id": "bed2", "name": "Bed 2", "area": 12},
            {"id": "bath", "name": "Bath", "area": 5, "max_aspect": 2.6},
            {"id": "hall", "name": "Hall", "area": 7, "max_aspect": 4.0},
        ],
        "adjacencies": [["hall", "living"], ["hall", "kitchen"], ["hall", "master"],
                        ["hall", "bed2"], ["master", "bath"]],
        "objects": [], "materials": [],
    }
    solved, _ = maybe_solve_layout(graph)
    return solved


def test_unfurnished_multiroom_still_renders():
    # A multi-room plan is the subject even with no furniture (the pipeline used
    # to bail because every solid was "structural").
    built = _build_and_raster(_apartment(), 800, 600)
    assert built is not None
    base_png, _depth, _normal, _hotspots, kind = built
    assert kind == "interior"
    assert base_png and len(base_png) > 1000          # real PNG bytes rendered


def test_empty_single_room_still_returns_none():
    # One bare room with no furniture → nothing meaningful → None (unchanged).
    graph = {
        "spaces": [{"id": "only", "dimensions": {"length": 5, "width": 4, "height": 2.8, "unit": "m"}}],
        "objects": [], "materials": [],
    }
    assert _build_and_raster(graph, 400, 300) is None


def _single_room_with(obj):
    return {"spaces": [{"id": "r", "name": "Living",
                        "dimensions": {"length": 5, "width": 4, "height": 2.8, "unit": "m"}}],
            "objects": [obj], "materials": []}


def test_furniture_authored_floating_is_floor_placed():
    # The LLM often authors an unreliable vertical coord (here y=2); furniture
    # must be dropped to the floor, not left floating.
    graph = _single_room_with({"id": "sofa", "type": "sofa",
                               "position": {"x": 2.5, "y": 2.0, "z": 2.0},
                               "dimensions": {"length": 2.0, "width": 0.9, "height": 0.8}})
    solids, _bbox, _kind = build_scene(graph)
    sofa = next(s for s in solids if s.id == "sofa")
    assert sofa.verts[:, 1].min() < 0.05          # base sits on the floor


def test_wall_mounted_object_keeps_its_height():
    graph = _single_room_with({"id": "tv", "type": "tv",
                               "position": {"x": 2.5, "y": 1.4, "z": 0.1},
                               "dimensions": {"length": 1.2, "width": 0.1, "height": 0.7}})
    solids, _bbox, _kind = build_scene(graph)
    tv = next(s for s in solids if s.id == "tv")
    assert tv.verts[:, 1].min() > 1.0             # kept its authored wall height


def test_furnished_single_room_still_renders():
    # A single room with furniture renders as before (the single-room path).
    graph = {
        "spaces": [{"id": "only", "name": "Living", "dimensions": {"length": 5, "width": 4, "height": 2.8, "unit": "m"}}],
        "objects": [{"id": "sofa", "type": "sofa", "position": {"x": 2.5, "y": 0, "z": 2},
                     "dimensions": {"length": 2.0, "width": 0.9, "height": 0.8}}],
        "materials": [],
    }
    built = _build_and_raster(graph, 800, 600)
    assert built is not None and built[4] == "interior"
