"""Multi-room behaviour for the architectural working views.

The single-room contract lives in test_architectural_views.py; this file proves
the views no longer collapse to spaces[0]. Fixtures use the real authored
conventions (length→X, width→Z for both rooms and objects) and run through
normalize_graph exactly as the save path does.
"""
from __future__ import annotations

import re

import pytest

from app.services.architectural_views_service import (
    generate_detail_package,
    generate_elevation_package,
    generate_isometric_package,
    generate_section_package,
)
from app.services.graph_normalizer import normalize_graph


def _apartment() -> dict:
    """3 rooms tiling to 9.6×4.5: LDK + Bedroom + Bathroom, one piece each."""
    raw = {
        "site": {"unit": "metric"},
        "style": {"primary": "Warm Contemporary"},
        "materials": [{"name": "Oak"}, {"name": "Plaster"}, {"name": "Gypsum"}],
        "spaces": [
            {"id": "ldk", "name": "Living Dining Kitchen", "room_type": "living_dining_kitchen",
             "position": {"x": 0.0, "z": 0.0}, "dimensions": {"length": 6.0, "width": 4.5, "height": 2.9}},
            {"id": "bed1", "name": "Bedroom", "room_type": "bedroom",
             "position": {"x": 6.0, "z": 0.0}, "dimensions": {"length": 3.6, "width": 3.2, "height": 2.9}},
            {"id": "bath1", "name": "Bathroom", "room_type": "bathroom",
             "position": {"x": 6.0, "z": 3.2}, "dimensions": {"length": 3.6, "width": 1.3, "height": 2.9}},
        ],
        "objects": [
            {"id": "sofa", "type": "sofa", "name": "Sofa", "role": "furniture",
             "position": {"x": 3.0, "y": 0.0, "z": 3.9}, "dimensions": {"length": 2.1, "width": 0.9, "height": 0.8}},
            {"id": "bed", "type": "bed", "name": "Bed", "role": "furniture",
             "position": {"x": 7.8, "y": 0.0, "z": 1.6}, "dimensions": {"length": 2.0, "width": 1.6, "height": 0.5}},
            {"id": "wc", "type": "toilet", "name": "WC", "role": "fixture",
             "position": {"x": 6.5, "y": 0.0, "z": 3.7}, "dimensions": {"length": 0.6, "width": 0.5, "height": 0.4}},
        ],
    }
    clean, _ = normalize_graph(raw)
    return clean


# ── Isometric ────────────────────────────────────────────────────────────────

def test_isometric_draws_every_room_not_just_the_first():
    out = generate_isometric_package(_apartment())
    assert out["summary"]["rooms"] == 3
    assert out["summary"]["orphans"] == 0
    svg = out["preview_svg"]
    # Three room floor quads (the isometric floor fill is #f3e9d8).
    assert svg.count("#f3e9d8") == 3
    # Every room is named (labels are truncated to fit, so match a stable stem),
    # and every piece of furniture is drawn (none floating off into no room).
    for name in ("Living Dining", "Bedroom", "Bathroom"):
        assert name in svg
    for piece in ("Sofa", "Wc"):
        assert piece in svg


def test_isometric_reports_building_envelope():
    out = generate_isometric_package(_apartment())
    # Envelope is the whole footprint, not one room: 9.6 (x) × 4.5 (z).
    assert out["summary"]["length_m"] == pytest.approx(9.6, abs=0.01)
    assert out["summary"]["width_m"] == pytest.approx(4.5, abs=0.01)
    assert out["summary"]["objects"] == 3


# ── Section (spec §3.3 worked example) ───────────────────────────────────────

def test_section_cuts_through_most_rooms_at_bbox_centre():
    out = generate_section_package(_apartment())
    s = out["summary"]
    # Candidates 2.25 / 1.6 / 3.85 all cross 2 rooms → tie broken to bbox centre 2.25.
    assert s["cut_at_m"] == pytest.approx(2.25, abs=0.01)
    assert s["rooms_in_cut"] == 2 and s["rooms_total"] == 3  # LDK + Bedroom, Bathroom absent


def test_section_draws_only_pierced_furniture_and_shares_walls():
    out = generate_section_package(_apartment())
    modes = {p["id"]: p["mode"] for p in out["placements"]}
    assert modes["bed"] == "cut"       # plane at z=2.25 passes through the bed (0.8–2.4)
    assert modes["sofa"] == "behind"   # sofa (3.45–4.35) is in a cut room but not pierced
    assert modes["wc"] == "off_cut"    # bathroom is not in the cut at all
    # Three poché blocks, not four: LDK|Bedroom share the x=6.0 wall (drawn once).
    assert out["preview_svg"].count("url(#poche)") == 3


def test_section_cut_line_is_overridable():
    # Force the cut into the bathroom's z-band; now it is the room shown.
    out = generate_section_package(_apartment(), cut_axis="z", cut_at=3.9)
    assert out["summary"]["cut_at_m"] == pytest.approx(3.9, abs=0.01)
    modes = {p["id"]: p["mode"] for p in out["placements"]}
    assert modes["wc"] in ("cut", "behind")   # the WC's room is now in the cut
    assert modes["bed"] == "off_cut"           # the bedroom's z-band (0–3.2) excludes 3.9


# ── Elevation (spec §3.4 worked example) ─────────────────────────────────────

def test_elevation_faces_the_longest_side_and_spans_full_width():
    out = generate_elevation_package(_apartment())
    s = out["summary"]
    assert s["face"] == "south"                       # x-extent 9.6 ≥ z-extent 4.5
    assert s["wall_length_m"] == pytest.approx(9.6, abs=0.01)   # full building width
    assert s["wall_height_m"] == pytest.approx(2.9, abs=0.01)   # tallest room sets the top
    # One silhouette block per room (stepped roofline), and no interior furniture.
    assert out["preview_svg"].count("#f6ede0") == 3
    assert out["preview_svg"].count("#d9c7b1") == 0   # furniture fill absent


def test_elevation_face_is_overridable_and_accounts_for_every_object():
    out = generate_elevation_package(_apartment(), face="west")
    assert out["summary"]["face"] == "west"
    assert out["summary"]["wall_length_m"] == pytest.approx(4.5, abs=0.01)  # z-extent now
    # Furniture is concealed on an exterior elevation but still accounted for.
    ids = {p["id"] for p in out["placements"]}
    assert {"sofa", "bed", "wc"} <= ids


# ── Detail (spec §3.5 option A) ──────────────────────────────────────────────

def test_detail_names_the_largest_room_as_its_subject():
    out = generate_detail_package(_apartment())
    # LDK (6.0×4.5 = 27 m²) is the largest, beating bedroom (11.5) and bath (4.7).
    assert out["summary"]["subject_room"] == "Living Dining Kitchen"
    assert "Living Dining Kitchen" in out["preview_svg"]


def test_detail_renders_for_single_room_too():
    single = {"spaces": [{"id": "s", "name": "Studio", "room_type": "studio",
                          "position": {"x": 0.0, "z": 0.0},
                          "dimensions": {"length": 3.0, "width": 3.0, "height": 2.7}}],
              "objects": []}
    out = generate_detail_package(single)
    assert out["summary"]["subject_room"] == "Studio"
    assert out["preview_svg"].startswith("<svg")
