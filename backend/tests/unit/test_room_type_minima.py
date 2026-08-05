"""Per-room-type code minima (fold-in).

NBC (and other codes) set different floor-area minimums for habitable rooms vs
kitchens vs baths vs WCs. The multi-room check now judges each room against the
minimum for its TYPE, so a small bath is no longer flagged against the 9.5 m²
habitable minimum. Service rooms with no stated figure are exempt.
"""

from __future__ import annotations

from app.services.layout_solver import maybe_solve_layout
from app.services.spatial.code_checks import (
    _min_area,
    _min_short,
    _pack_for,
    _room_category,
    run_code_checks,
)


# ── Classification ────────────────────────────────────────────────────────


def test_room_category_from_name():
    assert _room_category("Bath 1") == "bathroom"
    assert _room_category("Master Bathroom") == "bathroom"
    assert _room_category("Kitchen") == "kitchen"
    assert _room_category("WC") == "wc"
    assert _room_category("Powder Room") == "wc"
    assert _room_category("Living Room") == "habitable"
    assert _room_category("Master") == "habitable"
    assert _room_category("Bedroom 2") == "habitable"
    assert _room_category("Hall") == "service"
    assert _room_category("Corridor") == "service"
    assert _room_category("") == "habitable"          # unknown → conservative


# ── India carries per-type minima (sourced, not hardcoded here) ───────────


def test_india_per_type_area_minima():
    pack = _pack_for("india")
    assert _min_area(pack, "habitable") == 9.5
    assert _min_area(pack, "kitchen") == 4.5
    assert _min_area(pack, "bathroom") == 1.8
    assert _min_area(pack, "wc") == 1.1
    assert _min_area(pack, "service") is None         # exempt
    assert _min_short(pack, "kitchen") == 1.5
    assert _min_short(pack, "bathroom") is None        # no short-side figure → exempt


def test_jurisdiction_without_per_type_only_checks_habitable():
    pack = _pack_for("north_america")  # international_ibc — no per-category table
    assert _min_area(pack, "habitable") == pack["min_area_m2"]
    assert _min_area(pack, "bathroom") is None         # exempt (no bath minimum known)
    assert _min_area(pack, "service") is None


# ── Integration: a small bath is judged against the bath minimum ──────────


def test_small_bath_passes_against_its_own_minimum():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "area": 16},
            {"id": "kitchen", "name": "Kitchen", "area": 6},
            {"id": "bath", "name": "Bath", "area": 3, "max_aspect": 2.6},
        ],
        "adjacencies": [["living", "kitchen"], ["living", "bath"]],
    }
    solved, _ = maybe_solve_layout(graph)
    checks = run_code_checks(solved, region="india")
    area = next(c for c in checks if c["label"] == "Room area")
    # bath 3 m² ≥ 1.8 bath min, kitchen 6 ≥ 4.5, living 16 ≥ 9.5 → all pass
    assert area["status"] == "pass"


def test_undersized_habitable_room_still_warns():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "area": 16},
            {"id": "bed", "name": "Bedroom", "area": 6},   # below 9.5 habitable
            {"id": "bath", "name": "Bath", "area": 3, "max_aspect": 2.6},
        ],
        "adjacencies": [["living", "bed"], ["bed", "bath"]],
    }
    solved, _ = maybe_solve_layout(graph)
    area = next(c for c in run_code_checks(solved, region="india") if c["label"] == "Room area")
    assert area["status"] == "warn"                    # the bedroom is genuinely small
    assert "Bedroom" in area["note"]
