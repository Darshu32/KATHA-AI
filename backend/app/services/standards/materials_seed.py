"""Stage 3E (continued) — materials seed builder.

Translates :mod:`app.knowledge.materials` wood entries into
``building_standards`` rows tagged ``category='materials'``.

Why a new ``materials`` category?
  - BRD §1C separates material physical properties from clearance /
    space / MEP / code rules.
  - The existing five categories (space, clearance, mep, code,
    manufacturing) don't match the BRD's "material property" framing.
  - Per-material rows (walnut, oak, teak, plywood) live as siblings
    under ``subcategory='wood'`` with the BRD-wide band stored under
    ``subcategory='brd_band'``.

Slug naming
-----------
  - ``material_wood_brd_band`` — the BRD §1C wide envelope
    (600-900 kg/m³ density, MOR 50-100 MPa, etc.).
  - ``material_wood_<species>`` — one row per species (walnut, oak,
    teak, plywood_marine, mdf, rubberwood).

Only ``physical`` properties live in DB (density, MOR, MOE, finish
options, aesthetic). Cost + lead_time stay in ``material_prices``
(per the existing partial-deprecation note in ``app/knowledge/
materials.py``) — that table handles market-volatile values with
admin-versioned updates.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import materials as materials_kb


def _new_id() -> str:
    return uuid4().hex


def _serialise(value: Any) -> Any:
    """Coerce tuples → lists for JSON-friendly storage."""
    if isinstance(value, tuple):
        return [_serialise(v) for v in value]
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialise(v) for k, v in value.items()}
    return value


def _row(
    slug: str,
    *,
    display_name: str,
    data: dict[str, Any],
    subcategory: str,
    notes: str | None = None,
    source_section: str = "BRD §1C — Material physical properties",
    source_tag: str = "seed:materials",
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "slug": slug,
        "category": "materials",
        "jurisdiction": "india_nbc",
        "subcategory": subcategory,
        "display_name": display_name,
        "notes": notes,
        "data": _serialise(data),
        "source_section": source_section,
        "source_doc": "BRD-Phase-1",
        "source": source_tag,
    }


def _metal_brd_band_row() -> dict[str, Any]:
    """BRD §1C wide envelope for the primary metal palette
    (Steel, Aluminum, Brass). Stores per-metal expected values and
    the shared cost / finish / fabrication bands."""
    return _row(
        "material_metal_brd_band",
        display_name="Metals — BRD §1C envelope",
        subcategory="brd_band",
        data={
            "material_family": "metal",
            # Per-metal BRD-stated expectations (steel/aluminum/brass).
            # Density is a single point value per metal; yield is a band
            # for steel + aluminum and absent for brass (BRD calls out
            # non-magnetic instead of a yield band).
            "per_metal": dict(materials_kb.METALS_BRD_SPECS),
            "cost_inr_kg": list(materials_kb.METALS_BRD_COST_INR_KG),
            "finish_palette": list(materials_kb.METALS_BRD_FINISH_PALETTE),
            "fabrication_methods": list(materials_kb.METALS_BRD_FABRICATION),
        },
        notes=(
            "BRD §1C envelope for steel / aluminum / brass. Per-alloy rows "
            "may sit outside the cost band (mild steel below ₹150 floor; "
            "brass above ₹400 ceiling); the validator warns rather than "
            "fails when that happens."
        ),
    )


def _metal_alloy_rows() -> list[dict[str, Any]]:
    """One row per alloy in ``METALS``. Cost fields are dropped here
    (they belong in ``material_prices``); the validator-relevant
    physical properties (density, yield, ultimate) stay.
    """
    rows: list[dict[str, Any]] = []
    skip_keys = {"cost_inr_kg"}
    for alloy, spec in materials_kb.METALS.items():
        data = {"material_family": "metal", "alloy": alloy}
        for k, v in spec.items():
            if k in skip_keys:
                continue
            data[k] = v
        rows.append(
            _row(
                f"material_metal_{alloy}",
                display_name=f"Material — {alloy.replace('_', ' ').title()}",
                subcategory="metal",
                data=data,
            )
        )
    return rows


def _wood_brd_band_row() -> dict[str, Any]:
    """The single BRD-wide envelope row — the bands every wood is
    expected to sit inside (BRD §1C: density 600-900, MOR 50-100,
    MOE 8000-15000)."""
    return _row(
        "material_wood_brd_band",
        display_name="Wood — BRD §1C envelope",
        subcategory="brd_band",
        data={
            "material_family": "wood",
            **materials_kb.WOOD_BRD_RANGES,
            "finish_palette": list(materials_kb.WOOD_BRD_FINISH_PALETTE),
        },
        notes=(
            "BRD §1C wide envelope for the primary solid-wood palette. "
            "Per-species rows may sit outside this band on cost or strength "
            "(e.g. premium teak exceeds ₹800/kg ceiling); the validator "
            "warns rather than fails when that happens."
        ),
    )


def _wood_species_rows() -> list[dict[str, Any]]:
    """One row per species in ``WOOD``. Cost + lead_time fields are
    intentionally dropped here — they live in ``material_prices``.
    """
    rows: list[dict[str, Any]] = []
    skip_keys = {"cost_inr_kg", "lead_time_weeks"}
    for species, spec in materials_kb.WOOD.items():
        data = {"material_family": "wood", "species": species}
        for k, v in spec.items():
            if k in skip_keys:
                continue
            data[k] = v
        rows.append(
            _row(
                f"material_wood_{species}",
                display_name=f"Material — {species.replace('_', ' ').title()}",
                subcategory="wood",
                data=data,
            )
        )
    return rows


def build_materials_seed_rows() -> list[dict[str, Any]]:
    """Wood rows only — locked in migration ``0030_materials_wood_seed``.

    DO NOT add metal / fabric / finish rows here. Each material
    family has its own seed builder + migration so individual
    migrations stay idempotent. New families add their own
    ``build_<family>_seed_rows()`` function.
    """
    return [
        _wood_brd_band_row(),
        *_wood_species_rows(),
    ]


def build_metals_seed_rows() -> list[dict[str, Any]]:
    """Metals rows — BRD §1C envelope + per-alloy properties.

    Locked in migration ``0031_materials_metals_seed``.
    """
    return [
        _metal_brd_band_row(),
        *_metal_alloy_rows(),
    ]


# ─────────────────────────────────────────────────────────────────────
# Upholstery (BRD §1C — Leather, Fabric, Foam)
# ─────────────────────────────────────────────────────────────────────


def _upholstery_brd_band_row() -> dict[str, Any]:
    """BRD §1C envelope for leather / fabric / foam.

    Stores three sub-spec dicts (``leather``, ``fabric``, ``foam``)
    so the validator can look up a single row and resolve any of the
    three sub-families. Also carries the shared durability +
    colourfastness floors that apply across upholstery.

    Foam density / cost carry the BRD-stated values verbatim; a note
    documents the disagreement with commercial reality (HD36 is
    ~36 kg/m³ at ₹10-20k/m³, not BRD's 180 kg/m³ at ₹150-400/m³).
    """
    foam_note = (
        "BRD spec recorded verbatim. Commercial HD36 polyurethane foam is "
        "typically ~36 kg/m³ at ₹10,000–20,000 per m³; the validator does "
        "not check per-foam density against this BRD value — re-verify "
        "source before citing to client."
    )
    return _row(
        "material_upholstery_brd_band",
        display_name="Upholstery — BRD §1C envelope",
        subcategory="brd_band",
        data={
            "material_family": "upholstery",
            "leather": dict(materials_kb.UPHOLSTERY_LEATHER_BRD_SPEC),
            "fabric": dict(materials_kb.UPHOLSTERY_FABRIC_BRD_SPEC),
            "foam": dict(materials_kb.FOAM_BRD_SPEC),
            "durability_rubs": dict(materials_kb.UPHOLSTERY_DURABILITY_BRD),
            "colourfastness_min": int(materials_kb.UPHOLSTERY_COLOURFASTNESS_MIN),
        },
        notes=(
            "BRD §1C envelope for leather / fabric / foam. Foam density "
            "disagreement: "
            + foam_note
        ),
    )


def _upholstery_item_rows() -> list[dict[str, Any]]:
    """Per-item rows for every entry in ``UPHOLSTERY``. Subcategory is
    derived from the slug prefix (leather → leather, fabric → fabric).
    Cost stays in the row but isn't used by the validator (cost engine
    reads from ``material_prices`` separately).
    """
    rows: list[dict[str, Any]] = []
    for item, spec in materials_kb.UPHOLSTERY.items():
        # leather_genuine_grade_A → subcategory "leather"
        # fabric_cotton           → subcategory "fabric"
        if item.startswith("leather"):
            subcategory = "leather"
            material_family = "leather"
        elif item.startswith("fabric"):
            subcategory = "fabric"
            material_family = "fabric"
        else:
            subcategory = "upholstery"
            material_family = "upholstery"
        data = {
            "material_family": material_family,
            "item": item,
            **dict(spec),
        }
        rows.append(
            _row(
                f"material_upholstery_{item}",
                display_name=f"Material — {item.replace('_', ' ').title()}",
                subcategory=subcategory,
                data=data,
                notes=spec.get("notes") if isinstance(spec, dict) else None,
            )
        )
    return rows


def _foam_item_rows() -> list[dict[str, Any]]:
    """Per-grade foam rows. ``FOAM`` is a separate dict from
    ``UPHOLSTERY``; we tag them with subcategory=``foam`` so a
    sidebar can list foams independently."""
    rows: list[dict[str, Any]] = []
    for grade, spec in materials_kb.FOAM.items():
        data = {
            "material_family": "foam",
            "grade": grade,
            **dict(spec),
        }
        rows.append(
            _row(
                f"material_foam_{grade}",
                display_name=f"Material — Foam {grade}",
                subcategory="foam",
                data=data,
                notes=spec.get("brd_alignment") if isinstance(spec, dict) else None,
            )
        )
    return rows


def build_upholstery_seed_rows() -> list[dict[str, Any]]:
    """Upholstery rows — BRD §1C envelope + per-grade leather +
    per-type fabric + per-grade foam.

    Locked in migration ``0032_materials_upholstery_seed``.
    """
    return [
        _upholstery_brd_band_row(),
        *_upholstery_item_rows(),
        *_foam_item_rows(),
    ]


# ─────────────────────────────────────────────────────────────────────
# Finishes & coatings (BRD §1C continuation)
# ─────────────────────────────────────────────────────────────────────


def _finish_rows() -> list[dict[str, Any]]:
    """Per-finish rows from ``FINISHES``: lacquer, melamine, wax-oil,
    powder coat, anodise. Each row carries thickness / coats / cure /
    cost data verbatim from the literal.

    No standalone "finishes BRD band" row is seeded — the BRD finish
    palettes are already on the wood + metal BRD-band rows
    (``finish_palette`` field). This module just adds the technical
    spec data per finish.
    """
    rows: list[dict[str, Any]] = []
    for finish_name, spec in materials_kb.FINISHES.items():
        data = {
            "material_family": "finish",
            "finish": finish_name,
            **dict(spec),
        }
        rows.append(
            _row(
                f"material_finish_{finish_name}",
                display_name=f"Material — Finish {finish_name.replace('_', ' ').title()}",
                subcategory="finish",
                data=data,
            )
        )
    return rows


def build_finishes_seed_rows() -> list[dict[str, Any]]:
    """Finish rows for BRD §1C. Locked in migration
    ``0033_materials_finishes_seed``. Initial 5 finishes from the
    legacy ``FINISHES`` literal (lacquer / melamine / wax-oil /
    powder coat / anodise).
    """
    return list(_finish_rows())


# ─────────────────────────────────────────────────────────────────────
# Finishes — BRD §1C completion (migration 0034)
# ─────────────────────────────────────────────────────────────────────


_VARNISH_OIL_DATA: dict[str, Any] = {
    "material_family": "finish",
    "finish": "varnish_oil_based",
    "base": "oil",
    "coats": [2, 3],
    "thickness_microns": [40, 120],
    "sheen": ["matte", "satin", "gloss"],
    "cost_inr_m2": [180, 380],
    "notes": (
        "Oil-based varnish dries slowly (12-24h between coats) but builds "
        "a richer amber tone and deeper UV resistance than water-based."
    ),
}

_VARNISH_WATER_DATA: dict[str, Any] = {
    "material_family": "finish",
    "finish": "varnish_water_based",
    "base": "water",
    "coats": [2, 3],
    "thickness_microns": [25, 90],
    "sheen": ["matte", "satin", "gloss"],
    "cost_inr_m2": [200, 420],
    "notes": (
        "Water-based varnish dries fast (1-3h between coats), clear film, "
        "low VOC. Slightly less amber than oil-based."
    ),
}

_STAIN_DATA: dict[str, Any] = {
    "material_family": "finish",
    "finish": "stain",
    "bases": ["water", "oil", "alcohol"],
    "color_customisation": True,
    "coats": [1, 2],
    "cost_inr_m2": [80, 220],
    "notes": (
        "Stain penetrates the wood rather than building a film — apply "
        "before any sealing finish (lacquer / varnish). Water-based "
        "raises grain; oil-based is the smoothest; alcohol-based dries "
        "fastest but flashes off colour quickly."
    ),
}

_LEATHER_CARE_DATA: dict[str, Any] = {
    "material_family": "finish",
    "finish": "leather_care",
    "treatments": ["natural oil", "beeswax", "carnauba wax", "leather conditioner"],
    "uv_protection": True,
    "application_frequency_months": [3, 6],
    "cost_inr_m2": [40, 140],
    "notes": (
        "Periodic care — oil/wax treatments keep grade-A leather supple; "
        "UV-protective conditioner slows fade on sun-exposed surfaces. "
        "Not a primary finish — applied on top of cured leather hide."
    ),
}


def _finishes_completion_rows() -> list[dict[str, Any]]:
    """Four new finish rows added in migration 0034 to close BRD §1C
    coverage gaps: oil-based varnish, water-based varnish, stain (with
    base sub-types), and leather care.
    """
    payloads = (
        ("material_finish_varnish_oil_based", "Material — Finish Varnish (oil-based)", _VARNISH_OIL_DATA),
        ("material_finish_varnish_water_based", "Material — Finish Varnish (water-based)", _VARNISH_WATER_DATA),
        ("material_finish_stain", "Material — Finish Stain", _STAIN_DATA),
        ("material_finish_leather_care", "Material — Finish Leather care", _LEATHER_CARE_DATA),
    )
    rows: list[dict[str, Any]] = []
    for slug, display, data in payloads:
        rows.append(
            _row(
                slug,
                display_name=display,
                subcategory="finish",
                data=data,
                notes=data.get("notes"),
            )
        )
    return rows


def build_finishes_brd_completion_rows() -> list[dict[str, Any]]:
    """Locked in migration ``0034_materials_finishes_brd_completion``.
    Adds varnish (oil + water), stain, and leather care rows missing
    from migration 0033.
    """
    return list(_finishes_completion_rows())
