"""Async DB-backed Design Variations lookups (BRD §1C).

Mirrors ``materials_lookup`` and ``manufacturing_lookup``: read the
relevant ``building_standards`` row(s) under ``category='design'`` and
return the same shapes the legacy
:mod:`app.knowledge.variations` helpers returned, so existing callers
swap in transparently.

Five access patterns map to the five BRD sub-bullets:
  1. parametric_dim_flex_for(category)
  2. material_swap_family_for(material)
  3. style_adaptation_affinity(from_theme, to_theme)
  4. modular_options(family)
  5. customization_palette(axis)
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.standards import StandardsRepository


# ─────────────────────────────────────────────────────────────────────
# 1. Parametric — dimension flex per category
# ─────────────────────────────────────────────────────────────────────


async def parametric_dim_flex_for(
    session: AsyncSession,
    *,
    category: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, float]]:
    """Return ``{dim_name: flex_pct}`` for an item category.

    ``category`` is one of ``chair`` / ``table`` / ``bed`` /
    ``storage`` (matches ``ergonomics.CHAIRS`` etc).
    """
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"design_variation_parametric_{category.lower()}",
        category="design",
        jurisdiction=jurisdiction,
    )
    if not row:
        return None
    return dict((row.get("data") or {}).get("dimension_flex_pct") or {})


async def list_parametric_flex(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> dict[str, dict[str, float]]:
    """Return ``{category: {dim_name: flex_pct}}`` for every category."""
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="design",
        subcategory="variation_parametric",
        jurisdiction=jurisdiction,
    )
    out: dict[str, dict[str, float]] = {}
    for r in rows:
        d = r.get("data") or {}
        cat = d.get("category")
        if cat:
            out[cat] = dict(d.get("dimension_flex_pct") or {})
    return out


# ─────────────────────────────────────────────────────────────────────
# 2. Parametric — material swap families
# ─────────────────────────────────────────────────────────────────────


async def list_swap_families(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> dict[str, list[str]]:
    """Return ``{family: [member_slugs]}`` for every swap family."""
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="design",
        subcategory="variation_swap",
        jurisdiction=jurisdiction,
    )
    out: dict[str, list[str]] = {}
    for r in rows:
        d = r.get("data") or {}
        fam = d.get("family")
        if fam:
            out[fam] = list(d.get("members") or [])
    return out


async def compatible_materials(
    session: AsyncSession,
    material: str,
    *,
    jurisdiction: str = "india_nbc",
) -> list[str]:
    """Return swap candidates for a material across every family it
    appears in, deduped and preserving order. Empty when the material
    isn't catalogued in any swap family.
    """
    key = material.strip().lower().replace(" ", "_").replace("-", "_")
    families = await list_swap_families(session, jurisdiction=jurisdiction)
    matches: list[str] = []
    for members in families.values():
        if key in members:
            matches.extend(m for m in members if m != key)
    seen: set[str] = set()
    out: list[str] = []
    for m in matches:
        if m not in seen:
            out.append(m)
            seen.add(m)
    return out


# ─────────────────────────────────────────────────────────────────────
# 3. Style adaptations
# ─────────────────────────────────────────────────────────────────────


async def style_adaptation_affinity(
    session: AsyncSession,
    *,
    from_theme: str,
    to_theme: str,
    jurisdiction: str = "india_nbc",
) -> Optional[str]:
    """Return the affinity tag (``natural`` / ``moderate`` / ``open`` /
    custom) for a theme adaptation. ``None`` when neither the explicit
    pair nor the ``custom->*`` fallback is registered.
    """
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug="design_variation_style_affinity",
        category="design",
        jurisdiction=jurisdiction,
    )
    if not row:
        return None
    matrix = (row.get("data") or {}).get("affinity_matrix") or {}
    explicit = matrix.get(f"{from_theme}->{to_theme}")
    if explicit:
        return explicit
    if from_theme == "custom":
        return matrix.get("custom->*")
    return None


async def style_affinity_matrix(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> dict[str, str]:
    """Return the full ``{from->to: tag}`` affinity matrix."""
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug="design_variation_style_affinity",
        category="design",
        jurisdiction=jurisdiction,
    )
    if not row:
        return {}
    return dict((row.get("data") or {}).get("affinity_matrix") or {})


# ─────────────────────────────────────────────────────────────────────
# 4. Modular extensions
# ─────────────────────────────────────────────────────────────────────


async def modular_options(
    session: AsyncSession,
    family: str,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return the modular family spec + computed available spans.

    Spec carries module width, axis, joinery, and the BRD-supported
    configurations. ``available_spans`` enumerates every valid module
    count within the BRD min/max.
    """
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"design_variation_modular_{family}",
        category="design",
        jurisdiction=jurisdiction,
    )
    if not row:
        return None
    spec = dict(row.get("data") or {})
    mw = spec.get("module_width_mm")
    lo = spec.get("min_modules")
    hi = spec.get("max_modules")
    if mw and lo and hi:
        spec["available_spans"] = [
            {"modules": n, "linear_width_mm": n * mw}
            for n in range(int(lo), int(hi) + 1)
        ]
    return spec


async def list_modular_families(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> list[str]:
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="design",
        subcategory="variation_modular",
        jurisdiction=jurisdiction,
    )
    return sorted([
        (r.get("data") or {}).get("family")
        for r in rows
        if (r.get("data") or {}).get("family")
    ])


# ─────────────────────────────────────────────────────────────────────
# 5. Customization options
# ─────────────────────────────────────────────────────────────────────


async def customization_palette(
    session: AsyncSession,
    axis: str,
    *,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Return ``{options, cost_uplift_pct}`` for an axis
    (``color`` / ``finish`` / ``hardware``).
    """
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=f"design_variation_customization_{axis.lower()}",
        category="design",
        jurisdiction=jurisdiction,
    )
    if not row:
        return None
    d = row.get("data") or {}
    return {
        "options": list(d.get("options") or []),
        "cost_uplift_pct": dict(d.get("cost_uplift_pct") or {}),
    }


async def customization_summary(
    session: AsyncSession,
    *,
    jurisdiction: str = "india_nbc",
) -> dict[str, dict[str, Any]]:
    """Compact rollup of every customization axis — matches the legacy
    ``variations.customization_summary()`` shape:

    ``{axis: {options: [...], uplift_pct_band: {opt: [low, high]}}}``
    """
    repo = StandardsRepository(session)
    rows = await repo.list_active(
        category="design",
        subcategory="variation_customization",
        jurisdiction=jurisdiction,
    )
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        d = r.get("data") or {}
        axis = d.get("axis")
        if not axis:
            continue
        out[axis] = {
            "options": list(d.get("options") or []),
            "uplift_pct_band": dict(d.get("cost_uplift_pct") or {}),
        }
    return out


# ─────────────────────────────────────────────────────────────────────
# Composite: matches the legacy ``variations_for_item`` shape
# ─────────────────────────────────────────────────────────────────────


_MODULAR_ITEM_HINTS: tuple[tuple[str, str, str], ...] = (
    # (predicate_kind, hint, family) — predicate_kind is "contains" or "equals"
    ("contains", "sofa", "sofa_modular"),
    ("equals", "bookshelf", "shelving_modular"),
    ("equals", "object_shelf", "shelving_modular"),
    ("equals", "display_shelf", "shelving_modular"),
    ("equals", "kitchen_cabinet_base", "kitchen_base_modular"),
    ("equals", "kitchen_cabinet_wall", "kitchen_base_modular"),
    ("equals", "counter", "kitchen_base_modular"),
    ("equals", "wardrobe", "wardrobe_modular"),
)


def _modular_family_for_item(item: str) -> Optional[str]:
    item = (item or "").lower()
    for kind, hint, family in _MODULAR_ITEM_HINTS:
        if kind == "contains" and hint in item:
            return family
        if kind == "equals" and item == hint:
            return family
    return None


async def variations_for_item(
    session: AsyncSession,
    *,
    category: str,
    item: str,
    materials_in_use: tuple[str, ...] | list[str] = (),
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Aggregate variation envelope for a single item — DB-backed
    equivalent of :func:`app.knowledge.variations.variations_for_item`.

    Returns the same shape::

        {
            "category": ..., "item": ...,
            "parametric_dimension_ranges": {dim: {ergonomic_range, ...}},
            "material_swap_candidates": {material: [candidates]},
            "modular_family": {...} | None,
            "customization": {axis: {options, uplift_pct_band}},
        }
    """
    # Ergonomic ranges still come from the Python literal (separate BRD
    # bullet — Ergonomics, already validator-DB-backed via standards).
    # We only need the ranges for intersection; flex-pct comes from DB.
    from app.knowledge import ergonomics  # local import to dodge cycles

    cat_key = (category or "").lower()
    table = {
        "chair": ergonomics.CHAIRS,
        "table": ergonomics.TABLES,
        "bed": ergonomics.BEDS,
        "storage": ergonomics.STORAGE,
    }.get(cat_key) or {}
    spec = table.get(item) or {}

    flex_by_dim = await parametric_dim_flex_for(
        session, category=cat_key, jurisdiction=jurisdiction
    ) or {}

    dim_ranges: dict[str, dict[str, Any]] = {}
    for dim, raw in spec.items():
        if not (isinstance(raw, tuple) and len(raw) == 2):
            continue
        ergo_lo, ergo_hi = raw
        flex_pct = flex_by_dim.get(dim)
        if flex_pct is None:
            dim_ranges[dim] = {
                "category": cat_key,
                "item": item,
                "dim": dim,
                "ergonomic_range": list(raw),
                "flex_pct": None,
                "variation_range": list(raw),
            }
            continue
        nominal = (ergo_lo + ergo_hi) / 2.0
        flex = nominal * flex_pct / 100.0
        var_lo = max(ergo_lo, nominal - flex)
        var_hi = min(ergo_hi, nominal + flex)
        dim_ranges[dim] = {
            "category": cat_key,
            "item": item,
            "dim": dim,
            "ergonomic_range": list(raw),
            "flex_pct": flex_pct,
            "variation_range": [round(var_lo, 1), round(var_hi, 1)],
        }

    swap_candidates: dict[str, list[str]] = {}
    for m in materials_in_use:
        if not m:
            continue
        swap_candidates[m] = await compatible_materials(
            session, m, jurisdiction=jurisdiction
        )

    modular_family = _modular_family_for_item(item)
    modular = (
        await modular_options(session, modular_family, jurisdiction=jurisdiction)
        if modular_family
        else None
    )

    customization = await customization_summary(
        session, jurisdiction=jurisdiction
    )

    return {
        "category": cat_key,
        "item": item,
        "parametric_dimension_ranges": dim_ranges,
        "material_swap_candidates": swap_candidates,
        "modular_family": modular,
        "customization": customization,
    }
