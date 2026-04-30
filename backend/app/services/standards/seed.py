"""Deterministic seed builder for the Stage 3B ``building_standards`` table.

Translates :mod:`app.knowledge.clearances` and
:mod:`app.knowledge.space_standards` into row dicts ready for
``op.bulk_insert``.

Categories
----------
- ``clearance`` — doors, windows, corridors, stairs, ramps, circulation,
  egress.
- ``space`` — residential / commercial / hospitality room minimums.

Every seeded row is tagged ``jurisdiction = "india_nbc"`` (the BRD
baseline) and ``source_doc = "BRD-Phase-1"``. Specific NBC / IBC
section references are filled where the BRD or legacy module cites
them; everything else gets a generic ``"BRD Layer 1B"`` reference.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import clearances as clearances_kb
from app.knowledge import space_standards as space_kb


def _new_id() -> str:
    return uuid4().hex


def _band(value: Any) -> list[float] | None:
    """Coerce a (low, high) tuple/list into a JSON-friendly list."""
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return [float(v) for v in value]
    return [float(value), float(value)]


# ─────────────────────────────────────────────────────────────────────
# Clearances
# ─────────────────────────────────────────────────────────────────────


def _door_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in clearances_kb.DOORS.items():
        rows.append(
            {
                "id": _new_id(),
                "slug": f"door_{slug}",
                "category": "clearance",
                "jurisdiction": "india_nbc",
                "subcategory": "door",
                "display_name": f"{slug.replace('_', ' ').title()} Door",
                "notes": None,
                "data": {
                    "width_mm": _band(spec.get("width_mm")),
                    "height_mm": _band(spec.get("height_mm")),
                },
                "source_section": "BRD Layer 1B — clearance & egress",
                "source_doc": "BRD-Phase-1",
                "source": "seed:clearances.DOORS",
            }
        )
    return rows


def _window_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in clearances_kb.WINDOWS.items():
        rows.append(
            {
                "id": _new_id(),
                "slug": f"window_{slug}",
                "category": "clearance",
                "jurisdiction": "india_nbc",
                "subcategory": "window",
                "display_name": f"{slug.replace('_', ' ').title()} Window",
                "data": {
                    "width_mm": _band(spec.get("width_mm")),
                    "sill_height_mm": _band(spec.get("sill_height_mm")),
                },
                "source_section": "BRD Layer 1B — fenestration",
                "source_doc": "BRD-Phase-1",
                "source": "seed:clearances.WINDOWS",
            }
        )
    return rows


def _corridor_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in clearances_kb.CORRIDORS.items():
        rows.append(
            {
                "id": _new_id(),
                "slug": f"corridor_{slug}",
                "category": "clearance",
                "jurisdiction": "india_nbc",
                "subcategory": "corridor",
                "display_name": f"{slug.replace('_', ' ').title()} Corridor",
                "data": dict(spec),
                "source_section": "BRD Layer 1B — circulation",
                "source_doc": "BRD-Phase-1",
                "source": "seed:clearances.CORRIDORS",
            }
        )
    return rows


def _stair_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in clearances_kb.STAIRS.items():
        rows.append(
            {
                "id": _new_id(),
                "slug": f"stair_{slug}",
                "category": "clearance",
                "jurisdiction": "india_nbc",
                "subcategory": "stair",
                "display_name": f"{slug.replace('_', ' ').title()} Stair",
                "data": {
                    **dict(spec),
                    "rise_mm": _band(spec.get("rise_mm")),
                    "tread_mm": _band(spec.get("tread_mm")),
                },
                "source_section": (
                    "NBC 2016 Part 4 §5.3 (stairs)"
                    if slug in ("residential", "commercial")
                    else "NBC 2016 Part 4 §5.4 (fire egress)"
                ),
                "source_doc": "NBC-2016",
                "source": "seed:clearances.STAIRS",
            }
        )
    return rows


def _ramp_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in clearances_kb.RAMPS.items():
        rows.append(
            {
                "id": _new_id(),
                "slug": f"ramp_{slug}",
                "category": "clearance",
                "jurisdiction": "india_nbc",
                "subcategory": "ramp",
                "display_name": f"{slug.replace('_', ' ').title()} Ramp",
                "data": {
                    **dict(spec),
                    "handrail_height_mm": _band(spec.get("handrail_height_mm")),
                },
                "source_section": (
                    "NBC 2016 Part 3 (accessibility)"
                    if slug == "accessibility"
                    else "BRD Layer 1B"
                ),
                "source_doc": "NBC-2016" if slug == "accessibility" else "BRD-Phase-1",
                "source": "seed:clearances.RAMPS",
            }
        )
    return rows


def _circulation_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, value_mm in clearances_kb.CIRCULATION.items():
        rows.append(
            {
                "id": _new_id(),
                "slug": f"circulation_{slug}",
                "category": "clearance",
                "jurisdiction": "india_nbc",
                "subcategory": "circulation",
                "display_name": f"Circulation — {slug.replace('_', ' ').title()}",
                "data": {"clearance_mm": int(value_mm)},
                "source_section": "BRD Layer 1B — furniture circulation",
                "source_doc": "BRD-Phase-1",
                "source": "seed:clearances.CIRCULATION",
            }
        )
    return rows


def _egress_rows() -> list[dict[str, Any]]:
    """Egress is one ``slug=egress_general`` row carrying the whole rule set."""
    return [
        {
            "id": _new_id(),
            "slug": "egress_general",
            "category": "clearance",
            "jurisdiction": "india_nbc",
            "subcategory": "egress",
            "display_name": "General Egress Rules",
            "notes": "Travel distances, exit count, dead-end limits — BRD §1B",
            "data": dict(clearances_kb.EGRESS),
            "source_section": "NBC 2016 Part 4 §5 (egress)",
            "source_doc": "NBC-2016",
            "source": "seed:clearances.EGRESS",
        }
    ]


# ─────────────────────────────────────────────────────────────────────
# Space standards
# ─────────────────────────────────────────────────────────────────────


def _space_rows_for(table: dict[str, dict], subcategory: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for slug, spec in table.items():
        data = dict(spec)
        # Coerce range-style fields to JSON lists.
        for key in ("area_per_person_m2", "area_per_seat_m2", "area_per_customer_m2"):
            if key in data:
                data[key] = _band(data[key])
        rows.append(
            {
                "id": _new_id(),
                "slug": slug,
                "category": "space",
                "jurisdiction": "india_nbc",
                "subcategory": subcategory,
                "display_name": slug.replace("_", " ").title(),
                "notes": data.pop("notes", None),
                "data": data,
                "source_section": "BRD Layer 1B — space planning standards",
                "source_doc": "BRD-Phase-1",
                "source": f"seed:space_standards.{subcategory.upper().split('_')[0]}",
            }
        )
    return rows


def _residential_space_rows() -> list[dict[str, Any]]:
    return _space_rows_for(space_kb.RESIDENTIAL, "residential_room")


def _commercial_space_rows() -> list[dict[str, Any]]:
    return _space_rows_for(space_kb.COMMERCIAL, "commercial_room")


def _hospitality_space_rows() -> list[dict[str, Any]]:
    return _space_rows_for(space_kb.HOSPITALITY, "hospitality_room")


# ─────────────────────────────────────────────────────────────────────
# Public — single entry point
# ─────────────────────────────────────────────────────────────────────


def build_standards_seed_rows() -> list[dict[str, Any]]:
    """Every Stage 3B standards row, ready for ``op.bulk_insert``."""
    return [
        *_door_rows(),
        *_window_rows(),
        *_corridor_rows(),
        *_stair_rows(),
        *_ramp_rows(),
        *_circulation_rows(),
        *_egress_rows(),
        *_residential_space_rows(),
        *_commercial_space_rows(),
        *_hospitality_space_rows(),
    ]
