"""Async DB-backed material property lookups (BRD §1C).

Mirrors the existing ``ergonomics_lookup`` / ``codes_lookup`` /
``mep_sizing`` modules: fetch a row from ``building_standards`` and
validate a single property against the band stored on it.

Stage 1: wood only. Metals / fabrics / finishes follow the same
template once their seed migrations land.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.standards import StandardsRepository

# BRD §1C wood envelope — the single "what does the BRD say" row we
# validate every species against. Per-species rows carry the canonical
# point values (walnut density 640, MOR 100, etc.); the BRD-band row
# holds the wide tolerance window.
_WOOD_BRD_BAND_SLUG = "material_wood_brd_band"
_METAL_BRD_BAND_SLUG = "material_metal_brd_band"
_UPHOLSTERY_BRD_BAND_SLUG = "material_upholstery_brd_band"


_METAL_NUMERIC_PROPERTIES: tuple[str, ...] = ("density_kg_m3", "yield_mpa")


async def get_wood(
    session: AsyncSession,
    *,
    species: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the full property bag for a wood species.

    Example::

        spec = await get_wood(session, species="walnut")
        spec["density_kg_m3"]  # → 640
        spec["mor_mpa"]        # → 100
        spec["finish_options"] # → ["natural", "stain", …]

    The returned dict matches the ``data`` payload of the
    ``material_wood_<species>`` row.
    """
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"material_wood_{species}",
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def get_wood_brd_band(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the BRD §1C wide envelope row — the validator anchor.

    Includes density / MOR / MOE / cost / lead-time bands plus the
    canonical finish palette.
    """
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=_WOOD_BRD_BAND_SLUG,
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def list_woods(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    """All wood species seeded in the materials catalogue."""
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="materials",
        subcategory="wood",
        jurisdiction=jurisdiction,
    )
    return rows


async def check_wood_property(
    session: AsyncSession,
    *,
    species: str | None,
    property_key: str,
    value: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Validate one BRD §1C property of a wood against the envelope.

    ``property_key`` is the band key in the BRD row:
        ``density_kg_m3`` | ``mor_mpa`` | ``moe_mpa`` |
        ``cost_inr_kg`` | ``lead_time_weeks``.

    ``species`` is optional — pass it when you want the citation chip
    to mention the species (e.g. "walnut density 640 vs band 600-900").
    When omitted the check still works (against the BRD band) but the
    message is generic.

    Returns ``{status, message, reference, source_section,
    jurisdiction_used}`` matching the same shape as
    :func:`check_room_area` and friends.
    """
    repo = StandardsRepository(session)
    band_row = await repo.resolve(
        slug=_WOOD_BRD_BAND_SLUG,
        category="materials",
        jurisdiction=jurisdiction,
    )
    if band_row is None:
        return {
            "status": "unknown",
            "message": "BRD wood envelope row missing from DB.",
            "reference": None,
            "source_section": None,
        }
    band = band_row["data"].get(property_key)
    base = {
        "reference": band_row.get("notes") or band_row["display_name"],
        "source_section": band_row.get("source_section"),
        "jurisdiction_used": band_row["jurisdiction"],
    }
    if not isinstance(band, list) or len(band) != 2:
        return {
            **base,
            "status": "unknown",
            "message": f"BRD band for {property_key!r} is not a 2-tuple (got {band!r}).",
        }
    lo, hi = float(band[0]), float(band[1])
    label = species or "wood"
    if value < lo:
        return {
            **base,
            "status": "warn_low",
            "message": f"{label} {property_key}={value} below BRD band [{lo}, {hi}].",
        }
    if value > hi:
        return {
            **base,
            "status": "warn_high",
            "message": f"{label} {property_key}={value} above BRD band [{lo}, {hi}].",
        }
    return {**base, "status": "ok", "message": f"Within BRD band [{lo}, {hi}]."}


# ─────────────────────────────────────────────────────────────────────
# Metals (BRD §1C — Steel, Aluminum, Brass)
# ─────────────────────────────────────────────────────────────────────


async def get_metal(
    session: AsyncSession,
    *,
    alloy: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the full property bag for a metal alloy slug.

    Example::

        spec = await get_metal(session, alloy="aluminium_6061")
        spec["density_kg_m3"]  # → 2700
        spec["yield_mpa"]      # → [70, 200]
    """
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"material_metal_{alloy}",
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def get_metal_brd_band(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the BRD §1C metals envelope (per-metal expectations +
    shared cost / finish / fabrication bands)."""
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=_METAL_BRD_BAND_SLUG,
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def list_metals(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    """All metal alloys seeded in the materials catalogue."""
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="materials",
        subcategory="metal",
        jurisdiction=jurisdiction,
    )
    return rows


# Map alloy slug → BRD metal-family key (so steel grades all hit the
# same expectations row, etc.). BRD §1C names only steel/aluminum/brass
# at the family level.
_ALLOY_TO_FAMILY: dict[str, str] = {
    "mild_steel": "steel",
    "stainless_steel_304": "steel",
    "aluminium_6061": "aluminum",
    "brass": "brass",
}


async def check_metal_property(
    session: AsyncSession,
    *,
    alloy: str,
    property_key: str,
    value: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Validate one property of a metal alloy against the BRD family
    expectation.

    ``property_key`` is one of ``density_kg_m3`` or ``yield_mpa``.
    The BRD §1C envelope stores per-family values:
      - steel:    density 7850 kg/m³, yield 250-400 MPa
      - aluminum: density 2700 kg/m³, yield 70-200 MPa
      - brass:    density 8400 kg/m³ (non-magnetic; no yield band)

    Density is a single point value — we treat it as a ±5% tolerance.
    Yield is either a 2-element band or absent for the family.

    Returns the standard citation-carrying ``{status, message,
    reference, source_section, jurisdiction_used}`` shape.
    """
    repo = StandardsRepository(session)
    band_row = await repo.resolve(
        slug=_METAL_BRD_BAND_SLUG,
        category="materials",
        jurisdiction=jurisdiction,
    )
    if band_row is None:
        return {
            "status": "unknown",
            "message": "BRD metals envelope row missing from DB.",
            "reference": None,
            "source_section": None,
        }
    family = _ALLOY_TO_FAMILY.get(alloy)
    if family is None:
        return {
            "status": "unknown",
            "message": f"Alloy {alloy!r} not mapped to a BRD metal family.",
            "reference": None,
            "source_section": None,
        }
    per_metal = (band_row["data"].get("per_metal") or {}).get(family) or {}
    base = {
        "reference": band_row.get("notes") or band_row["display_name"],
        "source_section": band_row.get("source_section"),
        "jurisdiction_used": band_row["jurisdiction"],
    }
    expected = per_metal.get(property_key)

    # Density: point value with a ±5% tolerance (steel 7850 ±5% etc.).
    if property_key == "density_kg_m3":
        if not isinstance(expected, (int, float)):
            return {**base, "status": "unknown", "message": f"BRD has no density for {family!r}."}
        target = float(expected)
        tol = target * 0.05
        lo, hi = target - tol, target + tol
        if value < lo or value > hi:
            return {
                **base,
                "status": "warn_low" if value < lo else "warn_high",
                "message": (
                    f"{alloy} density={value} kg/m³ outside BRD {family} ±5% "
                    f"band [{lo:.0f}, {hi:.0f}]."
                ),
            }
        return {**base, "status": "ok", "message": f"Within ±5% of BRD {family} {target} kg/m³."}

    # Yield: band check when present.
    if property_key == "yield_mpa":
        if not isinstance(expected, list) or len(expected) != 2:
            return {
                **base,
                "status": "unknown",
                "message": f"BRD has no yield band for {family!r}.",
            }
        lo, hi = float(expected[0]), float(expected[1])
        if value < lo:
            return {
                **base,
                "status": "warn_low",
                "message": (
                    f"{alloy} yield={value} MPa below BRD {family} band [{lo}, {hi}]."
                ),
            }
        if value > hi:
            return {
                **base,
                "status": "warn_high",
                "message": (
                    f"{alloy} yield={value} MPa above BRD {family} band [{lo}, {hi}]."
                ),
            }
        return {**base, "status": "ok", "message": f"Within BRD {family} band [{lo}, {hi}]."}

    return {**base, "status": "unknown", "message": f"Unsupported property {property_key!r}."}


# ─────────────────────────────────────────────────────────────────────
# Upholstery (BRD §1C — Leather, Fabric, Foam)
# ─────────────────────────────────────────────────────────────────────


async def get_upholstery_brd_band(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """The BRD §1C envelope for leather + fabric + foam — three sub-spec
    dicts (``leather``, ``fabric``, ``foam``) plus shared durability and
    colourfastness floors."""
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=_UPHOLSTERY_BRD_BAND_SLUG,
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def get_leather(
    session: AsyncSession,
    *,
    grade: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Lookup a leather grade row by single letter (``A`` / ``B`` /
    ``C`` / ``D``). Returns the data payload from
    ``material_upholstery_leather_genuine_grade_<G>``."""
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"material_upholstery_leather_genuine_grade_{grade.upper()}",
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def get_fabric(
    session: AsyncSession,
    *,
    fabric_type: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Lookup a fabric type. ``fabric_type`` is one of ``cotton`` /
    ``linen`` / ``wool_blend`` / ``synthetic_blend`` /
    ``performance_poly`` — i.e. the slug suffix without the
    ``material_upholstery_fabric_`` prefix."""
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"material_upholstery_fabric_{fabric_type.lower()}",
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def get_foam(
    session: AsyncSession,
    *,
    grade: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Lookup a foam grade. ``grade`` is one of ``HD36`` / ``HR40`` /
    ``memory_foam``. NB: per-foam density / cost reflect commercial
    reality; BRD-stated values are on ``material_upholstery_brd_band``."""
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"material_foam_{grade}",
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def list_upholstery_items(
    session: AsyncSession,
    *,
    subcategory: str = "leather",
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    """List rows under one upholstery sub-family. ``subcategory`` is
    ``leather`` / ``fabric`` / ``foam``."""
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="materials",
        subcategory=subcategory,
        jurisdiction=jurisdiction,
    )
    return rows


async def check_upholstery_property(
    session: AsyncSession,
    *,
    family: str,
    property_key: str,
    value: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Validate one upholstery property against the BRD envelope.

    ``family`` ∈ ``leather`` / ``fabric``.
    ``property_key`` is one of:
      - leather:  ``thickness_mm`` | ``cost_inr_m2``
      - fabric:   ``cost_inr_m2``

    Returns the standard citation-carrying ``{status, message,
    reference, source_section, jurisdiction_used}`` shape.

    NB: foam density is intentionally not validated here — the BRD
    spec (180 kg/m³) disagrees with commercial reality (HD36 ~36
    kg/m³). See ``material_upholstery_brd_band.notes`` for context.
    Durability + colourfastness checks live separately as they apply
    across leather AND fabric.
    """
    repo = StandardsRepository(session)
    band_row = await repo.resolve(
        slug=_UPHOLSTERY_BRD_BAND_SLUG,
        category="materials",
        jurisdiction=jurisdiction,
    )
    if band_row is None:
        return {
            "status": "unknown",
            "message": "BRD upholstery envelope row missing from DB.",
            "reference": None,
            "source_section": None,
        }
    sub_spec = (band_row["data"].get(family) or {}) if family in {"leather", "fabric"} else {}
    base = {
        "reference": band_row.get("notes") or band_row["display_name"],
        "source_section": band_row.get("source_section"),
        "jurisdiction_used": band_row["jurisdiction"],
    }
    band = sub_spec.get(property_key)
    if not isinstance(band, list) or len(band) != 2:
        return {
            **base,
            "status": "unknown",
            "message": f"BRD has no {property_key!r} band for {family!r}.",
        }
    lo, hi = float(band[0]), float(band[1])
    if value < lo:
        return {
            **base,
            "status": "warn_low",
            "message": f"{family} {property_key}={value} below BRD band [{lo}, {hi}].",
        }
    if value > hi:
        return {
            **base,
            "status": "warn_high",
            "message": f"{family} {property_key}={value} above BRD band [{lo}, {hi}].",
        }
    return {**base, "status": "ok", "message": f"Within BRD band [{lo}, {hi}]."}


async def check_upholstery_durability(
    session: AsyncSession,
    *,
    rubs_k: float,
    is_commercial: bool = False,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Validate Martindale rubs (in thousands) against BRD §1C floors.

    BRD floor: 15K rubs for residential, 30K for commercial. Out-of-
    band emits ``warn_low``; otherwise ``ok``.
    """
    band = await get_upholstery_brd_band(session, jurisdiction=jurisdiction)
    if band is None:
        return {
            "status": "unknown",
            "message": "BRD upholstery envelope row missing from DB.",
            "reference": None,
            "source_section": None,
        }
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=_UPHOLSTERY_BRD_BAND_SLUG,
        category="materials",
        jurisdiction=jurisdiction,
    )
    base = {
        "reference": (row or {}).get("notes") or (row or {}).get("display_name"),
        "source_section": (row or {}).get("source_section"),
        "jurisdiction_used": (row or {}).get("jurisdiction") or jurisdiction,
    }
    durability = band.get("durability_rubs") or {}
    rubs_range = durability.get("rubs_range_k") or [15, 100]
    commercial_min = float(durability.get("commercial_min_k") or 30)
    floor = float(commercial_min if is_commercial else rubs_range[0])
    if rubs_k < floor:
        label = "commercial" if is_commercial else "residential"
        return {
            **base,
            "status": "warn_low",
            "message": (
                f"Upholstery durability {rubs_k}K rubs below BRD {label} "
                f"floor {floor:.0f}K."
            ),
        }
    return {**base, "status": "ok", "message": f"Above BRD floor {floor:.0f}K rubs."}


# ─────────────────────────────────────────────────────────────────────
# Finishes & coatings (BRD §1C continuation)
# ─────────────────────────────────────────────────────────────────────


# Recognised finish slugs (migrations 0033 + 0034). Used by the
# validator to detect finish strings in graph metadata.
KNOWN_FINISHES: tuple[str, ...] = (
    "lacquer_pu",
    "melamine",
    "wax_oil",
    "powder_coat",
    "anodise",
    # Added in migration 0034 — BRD §1C completion.
    "varnish_oil_based",
    "varnish_water_based",
    "stain",
    "leather_care",
)


async def get_finish(
    session: AsyncSession,
    *,
    finish: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Lookup a finish row by name. ``finish`` is one of
    :data:`KNOWN_FINISHES` (``lacquer_pu`` / ``melamine`` / ``wax_oil``
    / ``powder_coat`` / ``anodise``)."""
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"material_finish_{finish}",
        category="materials",
        jurisdiction=jurisdiction,
    )
    return row["data"] if row else None


async def list_finishes(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    """All finish rows seeded in the materials catalogue."""
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="materials",
        subcategory="finish",
        jurisdiction=jurisdiction,
    )
    return rows


async def resolve_finish_row(
    session: AsyncSession,
    *,
    finish: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Same as :func:`get_finish` but returns the full row (with
    citation fields) rather than only the data payload. Useful for
    the validator's INFO surface."""
    repo = StandardsRepository(session)
    return await repo.resolve(
        slug=f"material_finish_{finish}",
        category="materials",
        jurisdiction=jurisdiction,
    )
