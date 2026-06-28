"""Tests for the deterministic, graph-driven architectural views.

These replace the furniture-piece Section/Elevation/Isometric/Detail in the
``/design`` Views tab. The renderers consume the *normalized* graph, so the
fixtures here run through ``normalize_graph`` first — exactly as the save path
does — and the assertions check the output reflects the real room.
"""

from __future__ import annotations

import re

import pytest

from app.services.architectural_views_service import (
    CH,
    CW,
    generate_detail_package,
    generate_elevation_package,
    generate_isometric_package,
    generate_section_package,
)
from app.services.graph_normalizer import normalize_graph

_GENERATORS = [
    generate_section_package,
    generate_elevation_package,
    generate_isometric_package,
    generate_detail_package,
]


def _living_room() -> dict:
    raw = {
        "site": {"unit": "metric"},
        "style": {"primary": "Warm Contemporary"},
        "materials": [{"name": "Oak"}, {"name": "Plaster"}, {"name": "Gypsum"}],
        "spaces": [{"id": "s1", "room_type": "living_room",
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
        ],
    }
    clean, _ = normalize_graph(raw)
    return clean


@pytest.mark.parametrize("gen", _GENERATORS)
def test_returns_valid_svg(gen) -> None:
    out = gen(_living_room())
    svg = out["preview_svg"]
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert out["drawing_type"]
    assert "summary" in out


@pytest.mark.parametrize("gen", _GENERATORS)
def test_coordinates_within_canvas(gen) -> None:
    """Every numeric x/y coordinate must land inside the canvas (with margin)."""
    svg = gen(_living_room())["preview_svg"]
    for attr in ("x", "y", "x1", "y1", "x2", "y2", "cx", "cy"):
        for m in re.finditer(rf'\b{attr}="(-?\d+(?:\.\d+)?)"', svg):
            v = float(m.group(1))
            assert -80 <= v <= max(CW, CH) + 80, f"{attr}={v} out of canvas"


@pytest.mark.parametrize("gen", _GENERATORS)
def test_deterministic(gen) -> None:
    a = gen(_living_room())["preview_svg"]
    b = gen(_living_room())["preview_svg"]
    assert a == b


@pytest.mark.parametrize("gen", _GENERATORS)
def test_handles_empty_graph(gen) -> None:
    out = gen({})  # no spaces/objects — must not raise
    assert out["preview_svg"].startswith("<svg")


def test_section_reflects_ceiling_height() -> None:
    out = generate_section_package(_living_room())
    assert out["summary"]["ceiling_height_m"] == pytest.approx(2.75, abs=0.01)
    assert "2.75 m" in out["preview_svg"]  # ceiling dimension annotated


def test_elevation_detects_openings() -> None:
    out = generate_elevation_package(_living_room())
    assert out["summary"]["openings"] == 1
    assert "Window" in out["preview_svg"]


def test_isometric_reports_room_envelope() -> None:
    out = generate_isometric_package(_living_room())
    assert out["summary"]["length_m"] == pytest.approx(5.49, abs=0.01)
    assert out["summary"]["width_m"] == pytest.approx(4.27, abs=0.01)
    assert out["summary"]["objects"] == 3


def test_detail_sheet_cites_design_materials() -> None:
    out = generate_detail_package(_living_room())
    assert out["summary"]["materials_cited"][:3] == ["Oak", "Plaster", "Gypsum"]
    assert "Oak" in out["preview_svg"]
