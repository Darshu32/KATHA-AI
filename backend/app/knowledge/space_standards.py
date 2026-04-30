"""Space planning standards — minimum / typical areas per room or use.

⚠️ STAGE 3B DEPRECATION NOTICE — April 2026
--------------------------------------------
Values migrated to the ``building_standards`` DB table
(category=``space``). DB-backed accessors live in
:mod:`app.services.standards` (``check_room_area``,
``list_standards_by_category``, ``resolve_standard``).

This file remains as:
  1. Seed source for ``0007_stage3b_standards_seed``.
  2. Sync fallback / reference shape — no service currently imports
     it directly, but it documents the canonical room set.

DO NOT update values here. Use ``POST /admin/standards/...``.

---

Sourced from BRD Layer 1B and Neufert/Indian practice. All dimensions in
metres. Area in m^2.
"""

from __future__ import annotations

# Residential rooms: min area, typical area, min short-side, notes.
RESIDENTIAL: dict[str, dict] = {
    "bedroom": {
        "min_area_m2": 9.0,        # BRD: 3x3m
        "typical_area_m2": 12.0,
        "min_short_side_m": 2.7,
        "min_height_m": 2.7,
        "notes": "Master >= 12m^2 preferred; allow 0.6m circulation around bed.",
    },
    "kitchen": {
        "min_area_m2": 5.5,
        "typical_area_m2": 9.0,
        "min_short_side_m": 2.1,
        "min_height_m": 2.4,
        "notes": "Working width 2.5m min (per BRD). L/U shape preferred.",
    },
    "bathroom": {
        "min_area_m2": 3.0,
        "typical_area_m2": 5.0,
        "min_short_side_m": 1.2,
        "min_height_m": 2.4,
        "notes": "NBC: min 1.2x2.1m water-closet; ventilation required.",
    },
    "living_room": {
        "min_area_m2": 12.0,
        "typical_area_m2": 20.0,
        "min_short_side_m": 3.0,
        "min_height_m": 2.7,
        "notes": "Allow 2.4m TV viewing distance; 900mm circulation.",
    },
    "dining_room": {
        "min_area_m2": 9.0,
        "typical_area_m2": 12.0,
        "min_short_side_m": 2.7,
        "min_height_m": 2.7,
        "notes": "Allow 750mm around dining table for chair pull-out.",
    },
    "study": {
        "min_area_m2": 5.5,
        "typical_area_m2": 7.5,
        "min_short_side_m": 2.1,
        "min_height_m": 2.4,
        "notes": "Desk depth 600mm + 900mm chair clearance behind.",
    },
    "utility": {
        "min_area_m2": 2.5,
        "typical_area_m2": 4.0,
        "min_short_side_m": 1.2,
        "min_height_m": 2.4,
        "notes": "Ventilation + drainage required.",
    },
}

# Commercial — area per occupant or per function.
COMMERCIAL: dict[str, dict] = {
    "office_workstation": {
        "area_per_person_m2": (8.0, 10.0),  # BRD: 8-10 m^2 / person
        "min_short_side_m": 1.5,
        "notes": "Includes circulation; dense offices can go to 6 m^2/person.",
    },
    "meeting_room": {
        "min_area_m2": 15.0,
        "typical_area_m2": 30.0,
        "max_typical_m2": 50.0,
        "notes": "BRD: 30-50 m^2 typical; ~2.0 m^2 per seated participant.",
    },
    "conference_room": {
        "min_area_m2": 30.0,
        "typical_area_m2": 60.0,
        "notes": "2.5-3 m^2 per seat including circulation.",
    },
    "reception": {
        "min_area_m2": 10.0,
        "typical_area_m2": 18.0,
        "notes": "Desk + seating for 3-6 visitors.",
    },
    "retail_floor": {
        "area_per_customer_m2": (3.0, 5.0),
        "notes": "Exclude back-of-house; 1.2m main aisles minimum.",
    },
}

# Hospitality — per BRD.
HOSPITALITY: dict[str, dict] = {
    "hotel_room_standard": {
        "min_area_m2": 25.0,
        "typical_area_m2": 32.0,
        "max_typical_m2": 40.0,
        "min_short_side_m": 3.5,
        "notes": "BRD: 25-40 m^2 including bath.",
    },
    "hotel_suite": {
        "min_area_m2": 45.0,
        "typical_area_m2": 70.0,
        "notes": "Living + bedroom + bath.",
    },
    "restaurant_seating": {
        "area_per_seat_m2": (1.5, 2.0),  # BRD: 1.5-2 m^2 / seat
        "notes": "Fine dining upper bound; fast-casual lower bound.",
    },
    "restaurant_kitchen": {
        "ratio_of_seating_area": 0.35,
        "notes": "Back-of-house ~30-40% of dining area.",
    },
    "bar": {
        "area_per_seat_m2": (1.2, 1.6),
        "notes": "Includes bar front aisle.",
    },
}


def area_check(room_type: str, area_m2: float, segment: str = "residential") -> dict:
    """Return {status, message, reference} for a given area.

    status: 'ok' | 'warn_low' | 'warn_high' | 'unknown_room'
    """
    table = {
        "residential": RESIDENTIAL,
        "commercial": COMMERCIAL,
        "hospitality": HOSPITALITY,
    }.get(segment.lower())

    if not table or room_type not in table:
        return {"status": "unknown_room", "message": f"No standard for {segment}/{room_type}.", "reference": None}

    spec = table[room_type]
    min_area = spec.get("min_area_m2")
    max_area = spec.get("max_typical_m2")

    if min_area is not None and area_m2 < min_area:
        return {
            "status": "warn_low",
            "message": f"{room_type} area {area_m2:.1f} m^2 below minimum {min_area} m^2.",
            "reference": spec.get("notes"),
        }
    if max_area is not None and area_m2 > max_area * 1.5:
        return {
            "status": "warn_high",
            "message": f"{room_type} area {area_m2:.1f} m^2 significantly exceeds typical {max_area} m^2.",
            "reference": spec.get("notes"),
        }
    return {"status": "ok", "message": "Within standard range.", "reference": spec.get("notes")}
