"""Stage 3D — manufacturing seed builder.

Translates :mod:`app.knowledge.manufacturing` into ``building_standards``
rows (``category='manufacturing'``).

Subcategories
-------------
- ``tolerance``     — TOLERANCES dict (per-category ±mm)
- ``joinery``       — JOINERY dict (mortise-tenon, dovetail, …)
- ``welding``       — WELDING dict (GMAW, GTAW, brazing, spot weld)
- ``lead_time``     — LEAD_TIMES_WEEKS dict (per fab category)
- ``moq``           — MOQ dict (minimum order qty per category)
- ``qa_gate``       — QA_GATES list (5 BRD QC stages)
- ``process_spec``  — woodworking/metal/upholstery process BRDs
                       + precision_requirements + bending_rule

Slug naming convention
----------------------
- ``mfg_tolerance_<category>``       e.g. ``mfg_tolerance_structural``
- ``mfg_joinery_<type>``              e.g. ``mfg_joinery_mortise_tenon``
- ``mfg_welding_<method>``            e.g. ``mfg_welding_GMAW_MIG``
- ``mfg_lead_time_<category>``
- ``mfg_moq_<category>``
- ``mfg_qa_gate_<stage>``
- ``mfg_process_spec_<which>``        e.g. ``mfg_process_spec_woodworking``
- ``mfg_precision_requirements``      single row
- ``mfg_bending_rule``                single row
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import manufacturing as mfg_kb


def _new_id() -> str:
    return uuid4().hex


def _row(
    slug: str,
    *,
    subcategory: str,
    display_name: str,
    data: dict[str, Any],
    notes: str | None = None,
    source_section: str | None = None,
    source_doc: str = "BRD-Phase-1",
    source_tag: str = "seed:manufacturing",
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "slug": slug,
        "category": "manufacturing",
        "jurisdiction": "india_nbc",
        "subcategory": subcategory,
        "display_name": display_name,
        "notes": notes,
        "data": data,
        "source_section": source_section,
        "source_doc": source_doc,
        "source": source_tag,
    }


# ─────────────────────────────────────────────────────────────────────
# Tolerances
# ─────────────────────────────────────────────────────────────────────


def _tolerance_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"mfg_tolerance_{key}",
            subcategory="tolerance",
            display_name=f"Tolerance — {key.replace('_', ' ')}",
            data={
                "category": key,
                "tolerance_plus_minus_mm": float(spec["+-mm"]),
                "notes": spec.get("notes"),
            },
            notes=spec.get("notes"),
            source_section="BRD §3A — Precision Requirements",
            source_tag="seed:manufacturing.TOLERANCES",
        )
        for key, spec in mfg_kb.TOLERANCES.items()
    ]


def _precision_requirements_row() -> dict[str, Any]:
    return _row(
        "mfg_precision_requirements",
        subcategory="process_spec",
        display_name="Precision Requirements (BRD §3A)",
        data=dict(mfg_kb.PRECISION_REQUIREMENTS_BRD),
        notes="Universal tolerance bands cited by every drawing endpoint.",
        source_section="BRD §3A",
        source_tag="seed:manufacturing.PRECISION_REQUIREMENTS_BRD",
    )


# ─────────────────────────────────────────────────────────────────────
# Joinery
# ─────────────────────────────────────────────────────────────────────


def _joinery_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"mfg_joinery_{key}",
            subcategory="joinery",
            display_name=f"Joinery — {key.replace('_', ' ')}",
            data={"joinery_type": key, **dict(spec)},
            source_section="BRD §1C — Woodworking joinery",
            source_tag="seed:manufacturing.JOINERY",
        )
        for key, spec in mfg_kb.JOINERY.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# Welding
# ─────────────────────────────────────────────────────────────────────


def _welding_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"mfg_welding_{key}",
            subcategory="welding",
            display_name=f"Welding — {key.replace('_', ' ')}",
            data={"method": key, **dict(spec)},
            source_section="BRD §1C — Metal fabrication",
            source_tag="seed:manufacturing.WELDING",
        )
        for key, spec in mfg_kb.WELDING.items()
    ]


def _bending_rule_row() -> dict[str, Any]:
    return _row(
        "mfg_bending_rule",
        subcategory="process_spec",
        display_name="Metal — Minimum bending radius rule",
        data=dict(mfg_kb.BENDING_RULE),
        source_section="BRD §1C — Metal fabrication",
        source_tag="seed:manufacturing.BENDING_RULE",
    )


# ─────────────────────────────────────────────────────────────────────
# Lead times + MOQ
# ─────────────────────────────────────────────────────────────────────


def _lead_time_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"mfg_lead_time_{key}",
            subcategory="lead_time",
            display_name=f"Lead time — {key.replace('_', ' ')}",
            data={
                "category": key,
                "weeks_low": int(low),
                "weeks_high": int(high),
            },
            source_section="BRD §1C — manufacturing lead times",
            source_tag="seed:manufacturing.LEAD_TIMES_WEEKS",
        )
        for key, (low, high) in mfg_kb.LEAD_TIMES_WEEKS.items()
    ]


def _moq_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"mfg_moq_{key}",
            subcategory="moq",
            display_name=f"MOQ — {key.replace('_', ' ')}",
            data={"category": key, "min_order_qty": int(value)},
            source_section="BRD §1C — minimum order quantities",
            source_tag="seed:manufacturing.MOQ",
        )
        for key, value in mfg_kb.MOQ.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# QA gates
# ─────────────────────────────────────────────────────────────────────


def _qa_gate_rows() -> list[dict[str, Any]]:
    return [
        _row(
            f"mfg_qa_gate_{gate['stage']}",
            subcategory="qa_gate",
            display_name=f"QA gate — {gate['stage'].replace('_', ' ')}",
            data={
                "stage": gate["stage"],
                "brd_scope": gate["brd_scope"],
                "checks": list(gate["checks"]),
            },
            source_section="BRD §1C — Quality Gates",
            source_tag="seed:manufacturing.QA_GATES",
        )
        for gate in mfg_kb.QA_GATES
    ]


# ─────────────────────────────────────────────────────────────────────
# Process specs (whole-discipline rollups)
# ─────────────────────────────────────────────────────────────────────


def _process_spec_rows() -> list[dict[str, Any]]:
    return [
        _row(
            "mfg_process_spec_woodworking",
            subcategory="process_spec",
            display_name="Process spec — Woodworking",
            data=_serialise_process_spec(mfg_kb.WOODWORKING_BRD_SPEC),
            notes="BRD §1C canonical woodworking discipline.",
            source_section="BRD §1C",
            source_tag="seed:manufacturing.WOODWORKING_BRD_SPEC",
        ),
        _row(
            "mfg_process_spec_metal_fabrication",
            subcategory="process_spec",
            display_name="Process spec — Metal Fabrication",
            data=_serialise_process_spec(mfg_kb.METAL_FABRICATION_BRD_SPEC),
            notes="BRD §1C canonical metal fab discipline.",
            source_section="BRD §1C",
            source_tag="seed:manufacturing.METAL_FABRICATION_BRD_SPEC",
        ),
        _row(
            "mfg_process_spec_upholstery_assembly",
            subcategory="process_spec",
            display_name="Process spec — Upholstery Assembly",
            data=_serialise_process_spec(mfg_kb.UPHOLSTERY_ASSEMBLY_BRD_SPEC),
            notes="BRD §1C canonical upholstery discipline.",
            source_section="BRD §1C",
            source_tag="seed:manufacturing.UPHOLSTERY_ASSEMBLY_BRD_SPEC",
        ),
        _row(
            "mfg_process_spec_upholstery_detail",
            subcategory="process_spec",
            display_name="Process detail — Upholstery (operating spec)",
            data=_serialise_process_spec(mfg_kb.UPHOLSTERY_SPEC),
            notes="Operating-floor companion to upholstery process spec.",
            source_section="BRD §1C",
            source_tag="seed:manufacturing.UPHOLSTERY_SPEC",
        ),
        _row(
            "mfg_quality_gates_brd_spec",
            subcategory="process_spec",
            display_name="Quality Gates — BRD canonical sequence",
            data={"stages": list(mfg_kb.QUALITY_GATES_BRD_SPEC)},
            notes="The 5 BRD-mandated stages, in order.",
            source_section="BRD §1C — Quality Gates",
            source_tag="seed:manufacturing.QUALITY_GATES_BRD_SPEC",
        ),
    ]


def _serialise_process_spec(spec: dict[str, Any]) -> dict[str, Any]:
    """Coerce tuples → lists so the dict is JSON-serialisable."""
    out: dict[str, Any] = {}
    for k, v in spec.items():
        if isinstance(v, tuple):
            out[k] = list(v)
        elif isinstance(v, list):
            out[k] = [list(x) if isinstance(x, tuple) else x for x in v]
        elif isinstance(v, dict):
            out[k] = _serialise_process_spec(v)
        else:
            out[k] = v
    return out


# ─────────────────────────────────────────────────────────────────────
# Public — single entry point
# ─────────────────────────────────────────────────────────────────────


def build_manufacturing_seed_rows() -> list[dict[str, Any]]:
    """Every manufacturing-standards row, ready for ``op.bulk_insert``."""
    return [
        *_tolerance_rows(),
        _precision_requirements_row(),
        *_joinery_rows(),
        *_welding_rows(),
        _bending_rule_row(),
        *_lead_time_rows(),
        *_moq_rows(),
        *_qa_gate_rows(),
        *_process_spec_rows(),
    ]
