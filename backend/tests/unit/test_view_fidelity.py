"""Fidelity tests: every architectural view must faithfully depict the graph.

This is the answer to "I'm in software — I'll never know whether the drawings
are correct for the generated design." Correctness here means *fidelity*: every
object in the design appears in every relevant view, and every dimension printed
on the drawing equals the dimension in the graph. That is fully software-checked
below, so no architectural knowledge is needed to trust the views.

The fixtures are the same diverse, deliberately-flawed and clean designs the
normalizer harness uses — run through ``normalize_graph`` first, exactly as the
save path does.
"""

from __future__ import annotations

import pytest

from app.services.graph_normalizer import normalize_graph
from app.services.view_fidelity import (
    format_fidelity_report,
    verify_graph_views,
    verify_view,
)

# Reuse the multi-design fixtures from the normalizer harness.
from tests.unit.test_graph_normalizer import ALL_FIXTURES

_OBJECT_VIEWS = ["section_view", "elevation_view", "isometric_view"]


def _clean(name: str) -> dict:
    clean, _ = normalize_graph(ALL_FIXTURES[name]())
    return clean


@pytest.mark.parametrize("name", list(ALL_FIXTURES))
def test_every_design_passes_fidelity(name: str) -> None:
    report = verify_graph_views(_clean(name))
    assert report["ok"], format_fidelity_report(report)


@pytest.mark.parametrize("name", list(ALL_FIXTURES))
@pytest.mark.parametrize("view", _OBJECT_VIEWS)
def test_no_object_is_dropped_from_a_view(name: str, view: str) -> None:
    """Every non-wall object in the design must be drawn in every object view."""
    result = verify_view(view, _clean(name))
    assert not result["missing_from_view"], f"{view} dropped {result['missing_from_view']}"
    assert not result["not_in_design"], f"{view} drew phantom {result['not_in_design']}"


@pytest.mark.parametrize("name", list(ALL_FIXTURES))
@pytest.mark.parametrize("view", _OBJECT_VIEWS)
def test_annotated_dimensions_match_graph(name: str, view: str) -> None:
    """Numbers printed on the drawing equal the graph's room envelope."""
    result = verify_view(view, _clean(name))
    for check in result["dimension_checks"]:
        assert check["ok"], f"{view}:{check['dimension']} drawn={check['drawn']} graph={check['graph']}"


def test_dropped_object_is_detected(monkeypatch) -> None:
    """Guard the guard: if a renderer silently dropped an object, the verifier
    must FAIL rather than report a false PASS.

    We simulate a buggy section renderer that forgets one object's placement and
    confirm ``verify_view`` flags it as ``missing_from_view``.
    """
    graph = _clean("broken_axis_living_room")
    real = __import__(
        "app.services.view_fidelity", fromlist=["generate_section_package"]
    )

    def buggy_section(g: dict) -> dict:
        pkg = real.generate_section_package(g)
        pkg = dict(pkg)
        pkg["placements"] = pkg["placements"][1:]  # drop the first object
        return pkg

    monkeypatch.setitem(real._OBJECT_VIEWS, "section_view", buggy_section)
    result = verify_view("section_view", graph)
    assert result["missing_from_view"], "verifier failed to detect a dropped object"
    assert not result["ok"]


def test_report_formats_as_readable_table() -> None:
    report = verify_graph_views(_clean("clean_kitchen"))
    text = format_fidelity_report(report)
    assert "Overall fidelity: PASS" in text
    assert "section_view" in text
    assert "elevation_view" in text
    assert "isometric_view" in text
