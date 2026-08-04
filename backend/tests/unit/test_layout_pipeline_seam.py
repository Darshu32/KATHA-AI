"""Pipeline seam (cascade stage E — wiring).

``maybe_solve_layout`` is the single hook the generation pipeline calls. It must
be a strict no-op for everything the product emits today (one space) and only
solve a genuine, unplaced multi-room program — so turning it on can't regress
single-room generation.
"""

from __future__ import annotations

from app.services.layout_solver import maybe_solve_layout


# ── No-op cases (must not touch the graph) ────────────────────────────────


def test_single_space_is_untouched():
    graph = {"spaces": [{"id": "only", "dimensions": {"length": 5, "width": 4}}], "objects": []}
    out, solution = maybe_solve_layout(graph)
    assert solution is None
    assert out is graph                    # same object, not re-solved


def test_no_spaces_is_untouched():
    graph = {"objects": [{"id": "sofa"}]}
    out, solution = maybe_solve_layout(graph)
    assert solution is None and out is graph


def test_already_placed_multiroom_is_not_resolved():
    graph = {
        "spaces": [
            {"id": "a", "position": {"x": 0, "y": 0, "z": 0}, "dimensions": {"length": 4, "width": 3, "unit": "m"}},
            {"id": "b", "position": {"x": 4, "y": 0, "z": 0}, "dimensions": {"length": 4, "width": 3, "unit": "m"}},
        ]
    }
    out, solution = maybe_solve_layout(graph)
    assert solution is None and out is graph   # positions present → left alone


def test_malformed_graph_does_not_raise():
    for bad in ({}, {"spaces": "nope"}, {"spaces": [1, 2, 3]}):
        out, solution = maybe_solve_layout(bad)
        assert solution is None and out is bad


# ── Active case (a real multi-room program) ───────────────────────────────


def test_unplaced_multiroom_program_gets_solved():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "area": 24},
            {"id": "kitchen", "name": "Kitchen", "area": 12},
            {"id": "bed", "name": "Bed", "area": 14},
        ],
        "adjacencies": [["living", "kitchen"], ["living", "bed"]],
    }
    out, solution = maybe_solve_layout(graph)

    assert solution is not None
    assert len(solution.rooms) == 3
    # every space now carries a real position + dimensions
    for space in out["spaces"]:
        assert "position" in space and "dimensions" in space
        assert space["dimensions"]["unit"] == "m"
    # non-overlapping tiling invariant still holds end-to-end
    assert solution.max_area_error < 1e-6
    assert out.get("boundary")   # footprint recorded
