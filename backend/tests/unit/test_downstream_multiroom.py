"""Downstream multi-room awareness (cascade stage G).

Once the graph carries multiple placed rooms, the cost + checks must reflect the
WHOLE plan, not just the first space:
  * estimate area already sums every space (locked here so it can't regress),
  * MEP floor area now sums every room,
  * code checks run per-room and aggregate.
"""

from __future__ import annotations

import pytest

from app.services.estimation_engine import compute_estimate
from app.services.generation_pipeline import _total_floor_area_m2
from app.services.layout_solver import maybe_solve_layout
from app.services.spatial.code_checks import run_code_checks, tally


def _solved_apartment():
    graph = {
        "spaces": [
            {"id": "living", "name": "Living", "area": 24},
            {"id": "kitchen", "name": "Kitchen", "area": 12},
            {"id": "master", "name": "Master", "area": 16},
            {"id": "bath", "name": "Bath", "area": 5, "max_aspect": 2.6},
        ],
        "adjacencies": [["living", "kitchen"], ["master", "bath"]],
        "objects": [], "materials": [],
    }
    solved, _ = maybe_solve_layout(graph)
    return solved


# ── MEP floor area sums all rooms ─────────────────────────────────────────


def test_total_floor_area_sums_every_room():
    area = _total_floor_area_m2(_solved_apartment())
    assert area == pytest.approx(57.0, abs=0.5)   # 24 + 12 + 16 + 5


def test_total_floor_area_single_room_unchanged():
    graph = {"spaces": [{"id": "only", "dimensions": {"length": 6, "width": 4, "unit": "m"}}]}
    assert _total_floor_area_m2(graph) == pytest.approx(24.0)


def test_total_floor_area_legacy_room_shape():
    graph = {"room": {"dimensions": {"length": 5, "width": 4}}}
    assert _total_floor_area_m2(graph) == pytest.approx(20.0)


def test_total_floor_area_handles_mm():
    graph = {"spaces": [{"id": "r", "dimensions": {"length": 4500, "width": 3000}}]}
    assert _total_floor_area_m2(graph) == pytest.approx(13.5)  # 4.5 × 3.0


# ── Estimate already aggregates (lock it) ─────────────────────────────────


def test_estimate_area_sums_all_rooms():
    est = compute_estimate(_solved_apartment())
    # Rooms sum to 57 m²; the estimate reports TRUE square feet (m² → sqft, the
    # graph is metric while the ₹/sqft rates are imperial).
    assert est["area"]["total_sqft"] == pytest.approx(57.0 * 10.7639, rel=0.03)


# ── Code checks run per-room ──────────────────────────────────────────────


def test_code_checks_are_per_room_and_aggregate():
    checks = run_code_checks(_solved_apartment(), region="india")
    labels = [c["label"] for c in checks]
    assert "Ceiling height" in labels
    assert "Room area" in labels
    assert "Min room dimension" in labels

    ceiling = next(c for c in checks if c["label"] == "Ceiling height")
    assert ceiling["status"] == "pass"          # all rooms are 2.8 m ≥ NBC 2.75
    assert "rooms" in ceiling["note"]           # note reflects the whole plan

    # a small bath falling below the *habitable* area minimum must stay soft,
    # never a hard fail that flips the sheet to REVIEW
    _p, _w, fails = tally(checks)
    assert fails == 0

    # openings now exist → real egress + daylight checks (replaced the old
    # "pending" placeholder)
    assert "Egress" in labels and "Natural light" in labels
    egress = next(c for c in checks if c["label"] == "Egress")
    assert egress["status"] == "pass"           # every room reached by a door (from adjacencies)


def test_code_checks_single_room_still_opening_aware():
    # A single room keeps the full check set including the egress-door check.
    graph = {"spaces": [{"id": "only", "type": "living_room",
                         "dimensions": {"length": 5, "width": 4, "height": 2.8, "unit": "m"}}]}
    labels = [c["label"] for c in run_code_checks(graph, region="india")]
    assert "Ceiling height" in labels
    assert "Egress door" in labels or "Door clear width" in labels
