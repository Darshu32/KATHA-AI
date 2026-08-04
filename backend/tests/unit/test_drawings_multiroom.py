"""Multi-room 2D drawings (cascade stage D — drawings).

No code changed in ``drawings2d`` — it already cuts/projects whatever
``build_scene`` emits, so once the kernel went multi-room the plan/section/
elevation followed for free. These tests LOCK that: a solved plan must cut every
wall into the plan and compose a full sheet, so a future kernel change can't
silently drop it back to single-room.
"""

from __future__ import annotations

from app.services.layout_solver import (
    apply_layout_to_graph,
    program_from_graph,
    solve_layout,
)
from app.services.spatial.drawings2d import (
    _elevation_data,
    _plan_data,
    _section_data,
    plan_svg,
    sheet_svg,
)


def _multiroom_graph():
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
        "region": "india",
    }
    return apply_layout_to_graph(graph, solve_layout(program_from_graph(graph, seed=0)))


def test_plan_cuts_every_wall_not_just_one_room():
    pc, po, _sub = _plan_data(_multiroom_graph())
    # a single room's plan cut is ~4 wall polys; a 6-room plan has many more
    assert len(pc) >= 8
    assert len(po) > 0


def test_section_and_elevation_are_nonempty():
    mg = _multiroom_graph()
    sc, _so, _ = _section_data(mg, None)
    _ec, eo, _ = _elevation_data(mg)
    assert len(sc) > 0   # section passes through interior walls
    assert len(eo) > 0   # elevation silhouette exists


def test_plan_svg_has_drawn_paths():
    svg = plan_svg(_multiroom_graph())
    assert "<svg" in svg[:120]
    assert "<path" in svg          # actual geometry, not the empty placeholder
    assert "no geometry" not in svg


def test_sheet_composes_all_three_views_with_code_stamp():
    svg = sheet_svg(_multiroom_graph(), {"project_name": "Apartment", "region": "india",
                                          "scale": "1:100", "sheet": "A-101"})
    assert "<svg" in svg[:120]
    for view in ("PLAN", "SECTION", "ELEVATION"):
        assert view in svg
    # the geometry-true sheet still stamps a code verdict (on the primary room
    # for now — multi-room per-room checks are a later fold-in)
    assert "GENERAL ARRANGEMENT" in svg
    assert ("PASS" in svg) or ("REVIEW" in svg)
