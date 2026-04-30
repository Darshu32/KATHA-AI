"""Stage 3E — codes seed builder.

Translates four legacy modules into ``building_standards`` rows
tagged ``category='code'``:

- :mod:`app.knowledge.codes`       — NBC India + ECBC + accessibility +
                                       fire safety, jurisdiction
                                       ``india_nbc``.
- :mod:`app.knowledge.ibc`         — International Building Code 2021,
                                       jurisdiction ``international_ibc``.
- :mod:`app.knowledge.structural`  — IS-aligned structural loads + spans
                                       + seismic + foundations,
                                       jurisdiction ``india_nbc``.
- :mod:`app.knowledge.climate`     — NBC India climate-zone design rules,
                                       5 zones, jurisdiction ``india_nbc``.

Subcategories
-------------
- ``nbc``           — NBC India room dimensions, ventilation, staircase, …
- ``ecbc``          — Energy Conservation Building Code envelope targets
- ``accessibility`` — both NBC and IBC variants
- ``fire_safety``   — NBC India fire safety quick reference
- ``ibc``           — IBC 2021 generic structure (occupancy, construction,
                       egress, etc.)
- ``iecc``          — IECC envelope U-values per climate zone
- ``structural``    — live/dead/wind/seismic loads, span limits, foundations,
                       material strengths
- ``climate``       — 5 NBC India climate zones with full design strategy
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import climate as climate_kb
from app.knowledge import codes as codes_kb
from app.knowledge import ibc as ibc_kb
from app.knowledge import structural as structural_kb


def _new_id() -> str:
    return uuid4().hex


def _row(
    slug: str,
    *,
    subcategory: str,
    jurisdiction: str,
    display_name: str,
    data: dict[str, Any],
    notes: str | None = None,
    source_section: str | None = None,
    source_doc: str = "BRD-Phase-1",
    source_tag: str = "seed:codes",
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "slug": slug,
        "category": "code",
        "jurisdiction": jurisdiction,
        "subcategory": subcategory,
        "display_name": display_name,
        "notes": notes,
        "data": _serialise(data),
        "source_section": source_section,
        "source_doc": source_doc,
        "source": source_tag,
    }


def _serialise(value: Any) -> Any:
    """Recursively coerce tuples to lists for JSON-friendly storage."""
    if isinstance(value, tuple):
        return [_serialise(v) for v in value]
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialise(v) for k, v in value.items()}
    return value


# ─────────────────────────────────────────────────────────────────────
# NBC India (codes.NBC_INDIA)
# ─────────────────────────────────────────────────────────────────────


def _nbc_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rule_key, spec in codes_kb.NBC_INDIA.items():
        # Each NBC rule embeds a 'part' reference (e.g. "Part 3",
        # "Part 4"). Use it as source_section for citation.
        part_ref = spec.get("part")
        rows.append(
            _row(
                f"code_nbc_{rule_key}",
                subcategory="nbc",
                jurisdiction="india_nbc",
                display_name=f"NBC India — {rule_key.replace('_', ' ')}",
                data={k: v for k, v in spec.items() if k != "part"},
                source_section=f"NBC 2016 {part_ref}" if part_ref else None,
                source_doc="NBC-2016",
                source_tag="seed:codes.NBC_INDIA",
            )
        )
    return rows


def _ecbc_row() -> dict[str, Any]:
    return _row(
        "code_ecbc_envelope_targets",
        subcategory="ecbc",
        jurisdiction="india_nbc",
        display_name="ECBC — Envelope + lighting + chiller targets",
        data=dict(codes_kb.ECBC),
        notes=codes_kb.ECBC.get("notes"),
        source_section="ECBC 2017",
        source_doc="ECBC-2017",
        source_tag="seed:codes.ECBC",
    )


def _india_accessibility_row() -> dict[str, Any]:
    return _row(
        "code_accessibility_india_general",
        subcategory="accessibility",
        jurisdiction="india_nbc",
        display_name="Accessibility — India (Harmonised Guidelines + NBC Part 3)",
        data=dict(codes_kb.ACCESSIBILITY),
        source_section="Harmonised Guidelines 2021 + NBC Part 3",
        source_doc="HG-2021",
        source_tag="seed:codes.ACCESSIBILITY",
    )


def _india_fire_safety_row() -> dict[str, Any]:
    return _row(
        "code_fire_safety_india_general",
        subcategory="fire_safety",
        jurisdiction="india_nbc",
        display_name="Fire safety — India quick reference",
        data=dict(codes_kb.FIRE_SAFETY),
        source_section="NBC 2016 Part 4",
        source_doc="NBC-2016",
        source_tag="seed:codes.FIRE_SAFETY",
    )


# ─────────────────────────────────────────────────────────────────────
# IBC (ibc.py)
# ─────────────────────────────────────────────────────────────────────


def _ibc_occupancy_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"code_ibc_occupancy_{group}",
            subcategory="ibc_occupancy",
            jurisdiction="international_ibc",
            display_name=f"IBC Occupancy — Group {group}",
            data={"group": group, **dict(spec)},
            source_section="IBC 2021 Chapter 3",
            source_doc="IBC-2021",
            source_tag="seed:ibc.OCCUPANCY_GROUPS",
        )
        for group, spec in ibc_kb.OCCUPANCY_GROUPS.items()
    ]


def _ibc_construction_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"code_ibc_construction_{ctype.lower().replace('-', '_')}",
            subcategory="ibc_construction",
            jurisdiction="international_ibc",
            display_name=f"IBC Construction Type — {ctype}",
            data={"type": ctype, **dict(spec)},
            source_section="IBC 2021 Chapter 5",
            source_doc="IBC-2021",
            source_tag="seed:ibc.CONSTRUCTION_TYPES",
        )
        for ctype, spec in ibc_kb.CONSTRUCTION_TYPES.items()
    ]


def _ibc_singleton_rows() -> list[dict[str, Any]]:
    """One row per top-level IBC dict (egress, accessibility, …)."""
    return [
        _row(
            "code_ibc_egress",
            subcategory="ibc_egress",
            jurisdiction="international_ibc",
            display_name="IBC — Means of egress",
            data=dict(ibc_kb.EGRESS),
            source_section="IBC 2021 Chapter 10",
            source_doc="IBC-2021",
            source_tag="seed:ibc.EGRESS",
        ),
        _row(
            "code_ibc_accessibility",
            subcategory="accessibility",
            jurisdiction="international_ibc",
            display_name="IBC — Accessibility (cross-refs ANSI A117.1 / ADA)",
            data=dict(ibc_kb.ACCESSIBILITY),
            source_section="IBC 2021 Chapter 11",
            source_doc="IBC-2021",
            source_tag="seed:ibc.ACCESSIBILITY",
        ),
        _row(
            "code_ibc_live_loads",
            subcategory="structural",
            jurisdiction="international_ibc",
            display_name="IBC — Live loads (ASCE 7 alignment)",
            data={"loads_kn_per_m2": dict(ibc_kb.LIVE_LOADS_KN_PER_M2)},
            source_section="IBC 2021 Chapter 16 / ASCE 7",
            source_doc="IBC-2021",
            source_tag="seed:ibc.LIVE_LOADS_KN_PER_M2",
        ),
        _row(
            "code_ibc_interior_environment",
            subcategory="ibc_environment",
            jurisdiction="international_ibc",
            display_name="IBC — Interior environment minima",
            data=dict(ibc_kb.INTERIOR_ENVIRONMENT),
            source_section="IBC 2021 Chapter 12",
            source_doc="IBC-2021",
            source_tag="seed:ibc.INTERIOR_ENVIRONMENT",
        ),
    ]


def _iecc_envelope_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"code_iecc_envelope_{zone_key}",
            subcategory="iecc",
            jurisdiction="international_ibc",
            display_name=f"IECC — Envelope U-values, {zone_key.replace('_', ' ')}",
            data={"climate_zone": zone_key, **dict(spec)},
            source_section="IECC envelope targets",
            source_doc="IECC",
            source_tag="seed:ibc.ENERGY_ENVELOPE_U_VALUES_W_M2K",
        )
        for zone_key, spec in ibc_kb.ENERGY_ENVELOPE_U_VALUES_W_M2K.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# Structural (structural.py)
# ─────────────────────────────────────────────────────────────────────


def _structural_rows() -> list[dict[str, Any]]:
    """Each top-level dict becomes a single row keyed by topic."""
    return [
        _row(
            "code_structural_live_loads_is875",
            subcategory="structural",
            jurisdiction="india_nbc",
            display_name="Structural — Live loads (IS 875 Part 2)",
            data={"loads_kn_per_m2": dict(structural_kb.LIVE_LOADS_KN_PER_M2)},
            source_section="IS 875 Part 2",
            source_doc="IS-875",
            source_tag="seed:structural.LIVE_LOADS_KN_PER_M2",
        ),
        _row(
            "code_structural_dead_loads",
            subcategory="structural",
            jurisdiction="india_nbc",
            display_name="Structural — Dead loads (typical)",
            data={"loads_kn_per_m2": dict(structural_kb.DEAD_LOADS_KN_PER_M2)},
            source_section="IS 875 Part 1",
            source_doc="IS-875",
            source_tag="seed:structural.DEAD_LOADS_KN_PER_M2",
        ),
        _row(
            "code_structural_wind_loads_is875",
            subcategory="structural",
            jurisdiction="india_nbc",
            display_name="Structural — Wind loads (basic)",
            data={"loads_kn_per_m2": dict(structural_kb.WIND_LOADS_KN_PER_M2)},
            source_section="IS 875 Part 3",
            source_doc="IS-875",
            source_tag="seed:structural.WIND_LOADS_KN_PER_M2",
        ),
        _row(
            "code_structural_seismic_zones_is1893",
            subcategory="structural",
            jurisdiction="india_nbc",
            display_name="Structural — Seismic zones (IS 1893)",
            data={"zones": _serialise(structural_kb.SEISMIC_ZONES)},
            source_section="IS 1893 Part 1",
            source_doc="IS-1893",
            source_tag="seed:structural.SEISMIC_ZONES",
        ),
        _row(
            "code_structural_column_spacing",
            subcategory="structural",
            jurisdiction="india_nbc",
            display_name="Structural — Column spacing recommendations",
            data={"spacing_m": _serialise(structural_kb.COLUMN_SPACING_M)},
            notes="BRD §1B: 5–8 m optimal for buildings.",
            source_section="BRD §1B + IS 456",
            source_doc="BRD-Phase-1",
            source_tag="seed:structural.COLUMN_SPACING_M",
        ),
        _row(
            "code_structural_span_limits",
            subcategory="structural",
            jurisdiction="india_nbc",
            display_name="Structural — Span limits by material",
            data={"span_m": _serialise(structural_kb.SPAN_LIMITS_M)},
            source_section="IS 456 / IS 800 / IS 883",
            source_doc="BRD-Phase-1",
            source_tag="seed:structural.SPAN_LIMITS_M",
        ),
        _row(
            "code_structural_foundation_by_soil",
            subcategory="structural",
            jurisdiction="india_nbc",
            display_name="Structural — Foundation guidance by soil bearing capacity",
            data=_serialise(structural_kb.FOUNDATION_BY_SOIL),
            source_section="IS 1904 / soil mechanics",
            source_doc="IS-1904",
            source_tag="seed:structural.FOUNDATION_BY_SOIL",
        ),
        _row(
            "code_structural_material_strengths",
            subcategory="structural",
            jurisdiction="india_nbc",
            display_name="Structural — Material strengths (concrete + steel)",
            data=_serialise(structural_kb.MATERIAL_STRENGTHS_MPA),
            source_section="IS 456 / IS 800 / IS 1786",
            source_doc="IS-456",
            source_tag="seed:structural.MATERIAL_STRENGTHS_MPA",
        ),
    ]


# ─────────────────────────────────────────────────────────────────────
# Climate zones (climate.py)
# ─────────────────────────────────────────────────────────────────────


def _climate_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"code_climate_{zone_key}",
            subcategory="climate",
            jurisdiction="india_nbc",
            display_name=f"Climate zone — {pack['display_name']}",
            data=_serialise(pack),
            notes=f"Regions: {', '.join(pack.get('typical_regions', []))}",
            source_section="SP 41 / NBC 2016 Part 11",
            source_doc="NBC-2016",
            source_tag="seed:climate.ZONES",
        )
        for zone_key, pack in climate_kb.ZONES.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# Public — single entry point
# ─────────────────────────────────────────────────────────────────────


def build_codes_seed_rows() -> list[dict[str, Any]]:
    """Every Stage 3E ``code`` row, ready for ``op.bulk_insert``."""
    return [
        # NBC India
        *_nbc_rows(),
        _ecbc_row(),
        _india_accessibility_row(),
        _india_fire_safety_row(),
        # IBC + IECC
        *_ibc_occupancy_rows(),
        *_ibc_construction_rows(),
        *_ibc_singleton_rows(),
        *_iecc_envelope_rows(),
        # Structural (IS-aligned, India)
        *_structural_rows(),
        # Climate zones (India)
        *_climate_rows(),
    ]
