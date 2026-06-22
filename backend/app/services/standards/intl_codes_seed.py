"""International codes seed — Europe (Eurocode/DIN) + Middle East (UAE/Dubai).

KATHA serves architects worldwide. Stage 3E seeded India (``india_nbc``)
and an IBC baseline (``international_ibc``). This module adds two
demo-critical jurisdictions so the compliance panel cites the *right*
codes for the CEO's Germany + Dubai client demos:

- ``eu_eurocode`` — Eurocodes (EN 1990–1999) with German DIN / GEG
  energy + DIN 18040 accessibility + DIN 14676 fire detection.
- ``uae_dubai``   — Dubai Green Building Regs (Al Sa'fat) + Dubai
  Universal Design Code + UAE Fire & Life Safety Code.

The compliance advisory panel (``generation_pipeline._compliance_advisories``)
resolves three fixed slugs per jurisdiction:
  * ``code_ecbc_envelope_targets``        (envelope U-values + WWR)
  * ``code_accessibility_india_general``  (ramp slope + door clear width)
  * ``code_fire_safety_india_general``    (smoke detector trigger)

We seed those exact slugs under each new jurisdiction so the resolver
picks the region-specific row instead of falling back to the Indian
baseline. Values are indicative regulatory targets with real citations —
accurate enough for a credible client demo; flagged as targets in notes.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


def _new_id() -> str:
    return uuid4().hex


def _row(
    slug: str,
    *,
    jurisdiction: str,
    subcategory: str,
    display_name: str,
    data: dict[str, Any],
    source_section: str,
    source_doc: str,
    notes: str | None = None,
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "slug": slug,
        "category": "code",
        "jurisdiction": jurisdiction,
        "subcategory": subcategory,
        "display_name": display_name,
        "notes": notes,
        "data": data,
        "source_section": source_section,
        "source_doc": source_doc,
        "source": "seed:intl_codes",
    }


# ─────────────────────────────────────────────────────────────────────
# Europe — Eurocode + German DIN / GEG
# ─────────────────────────────────────────────────────────────────────


def _europe_rows() -> list[dict[str, Any]]:
    return [
        _row(
            "code_ecbc_envelope_targets",
            jurisdiction="eu_eurocode",
            subcategory="energy",
            display_name="Energy envelope — Germany GEG 2020 (EnEV successor)",
            data={
                # GEG 2020 / EnEV reference U-values for new residential.
                "envelope_U_value_wall_w_m2k": 0.24,
                "envelope_U_value_roof_w_m2k": 0.20,
                "envelope_U_value_window_w_m2k": 1.30,
                "window_wall_ratio_max": 0.40,
            },
            notes="Indicative GEG 2020 reference values for new build; "
            "EPBD nZEB targets apply across the EU.",
            source_section="GEG 2020 §16 / EnEV Anlage 1",
            source_doc="GEG-2020",
        ),
        _row(
            "code_accessibility_india_general",
            jurisdiction="eu_eurocode",
            subcategory="accessibility",
            display_name="Accessibility — DIN 18040 (barrier-free building)",
            data={
                # DIN 18040-1: ramps max 6 % gradient; clear door width.
                "ramp_slope_max_ratio": 0.06,
                "doorway_clear_width_mm": 900,
                "corridor_min_width_mm": 1500,
            },
            notes="DIN 18040-1/-2 barrier-free construction; aligns with "
            "EN 17210 accessibility of the built environment.",
            source_section="DIN 18040-1 §4.3 / EN 17210",
            source_doc="DIN-18040",
        ),
        _row(
            "code_fire_safety_india_general",
            jurisdiction="eu_eurocode",
            subcategory="fire_safety",
            display_name="Fire safety — German MBO + DIN 14676 detection",
            data={
                "smoke_detector": "Required in bedrooms, children's rooms "
                "and escape corridors (DIN 14676 / Landesbauordnung).",
                "fire_resistance_eurocode": "EN 1991-1-2 / EN 1992-1-2 "
                "structural fire design.",
            },
            notes="Smoke-alarm obligation per state Landesbauordnung; "
            "structural fire design per Eurocode EN 199x-1-2.",
            source_section="MBO §14 / DIN 14676 / EN 1991-1-2",
            source_doc="MBO-DIN-14676",
        ),
    ]


# ─────────────────────────────────────────────────────────────────────
# Middle East — UAE / Dubai
# ─────────────────────────────────────────────────────────────────────


def _middle_east_rows() -> list[dict[str, Any]]:
    return [
        _row(
            "code_ecbc_envelope_targets",
            jurisdiction="uae_dubai",
            subcategory="energy",
            display_name="Energy envelope — Dubai Green Building (Al Sa'fat)",
            data={
                # Dubai Green Building Regs — hot-climate envelope limits.
                "envelope_U_value_wall_w_m2k": 0.57,
                "envelope_U_value_roof_w_m2k": 0.30,
                "envelope_U_value_glazing_w_m2k": 2.10,
                "glazing_shgc_max": 0.40,
                "window_wall_ratio_max": 0.40,
            },
            notes="Dubai Green Building Regulations & Specifications "
            "(Al Sa'fat); Estidama Pearl applies in Abu Dhabi.",
            source_section="Dubai Green Building Regs — Resource Effectiveness",
            source_doc="Dubai-Al-Safat",
        ),
        _row(
            "code_accessibility_india_general",
            jurisdiction="uae_dubai",
            subcategory="accessibility",
            display_name="Accessibility — Dubai Universal Design Code",
            data={
                # Dubai Universal Design Code 2021 — ramp 1:12, doors ≥ 900.
                "ramp_slope_max_ratio": 0.0833,
                "doorway_clear_width_mm": 900,
                "corridor_min_width_mm": 1500,
            },
            notes="Dubai Universal Design Code 2021 (My Community … "
            "A City for Everyone).",
            source_section="Dubai Universal Design Code 2021 §3",
            source_doc="Dubai-UDC-2021",
        ),
        _row(
            "code_fire_safety_india_general",
            jurisdiction="uae_dubai",
            subcategory="fire_safety",
            display_name="Fire safety — UAE Fire & Life Safety Code",
            data={
                "smoke_detector": "Required throughout per UAE Fire & Life "
                "Safety Code of Practice (Civil Defence).",
                "sprinklers": "Required per occupancy & height thresholds "
                "(UAE FLS Code Ch. 1-3).",
            },
            notes="UAE Fire & Life Safety Code of Practice 2018, "
            "enforced by Dubai Civil Defence.",
            source_section="UAE FLS Code of Practice 2018",
            source_doc="UAE-FLS-2018",
        ),
    ]


def build_intl_codes_seed_rows() -> list[dict[str, Any]]:
    """All Europe + Middle East ``code`` rows, ready for ``op.bulk_insert``."""
    return [*_europe_rows(), *_middle_east_rows()]


__all__ = ["build_intl_codes_seed_rows"]
