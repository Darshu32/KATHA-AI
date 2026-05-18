"""Aggregator that pre-loads everything the MEP Spec Sheet LLM stage
cites — BRD §3D.

Produces a single ``mep_kb`` dict shaped exactly like what
:func:`mep_spec_service.build_mep_spec_knowledge` previously read from
:mod:`app.knowledge.mep` literals, but every value now sources from
versioned ``building_standards`` (under ``category='mep'``) +
``city_price_index`` rows.

Caller passes the result into
``build_mep_spec_knowledge(..., mep_kb=pack)``. Builder falls back to
the legacy literal per key when a sub-dict is missing.

Pack shape (matches the legacy literal reads 1-for-1):

    {
      "hvac_brd": {
          "ach_table": {room: ach_float},
          "cfm_per_person_table": {use: cfm_int},
          "cooling_load_tr_per_m2": {use: tr_per_m2_float},
          "duct_velocity_m_s": {zone: [low, high]},
          "btu_per_tr": float,
          "kw_per_tr": float,
          "equipment_band_tr": [{capacity_tr, label}],
          "duct_round_chart_mm_by_cfm": [{cfm_max, diameter_mm}],
          "register_cfm_rating": {register_key: cfm_int},
      },
      "hvac_pre_calc": {...},          # pre-computed sizings
      "electrical_brd": {
          "lux_levels": {use_kind: lux_int},
          "circuit_load_w": {circuit: load_int},
          "power_density_w_per_m2": {use: int},
          "fixture_catalogue": {fixture: {watts, lumens, ...}},
          "outlet_catalogue": {outlet: {phase, rating_a, ...}},
          "outlet_count_rule": {...},
          "task_lighting_recipe": {use: [zones]},
          "lighting_layout_rules": {...},
      },
      "electrical_pre_calc": {...},
      "plumbing_brd": {
          "dfu_per_fixture": {fixture: dfu_int},
          "pipe_size_mm_by_dfu": [{dfu_max, pipe_mm}],
          "slope_per_metre": {...},
          "slope_requirement": {category: {...}},
          "water_demand_lpd": {use: [low, high]},
          "wsfu_per_fixture": {fixture: {hot, cold, total}},
          "hunters_curve_flush_tank": [{wsfu, gpm}],
          "supply_pipe_size_mm_by_gpm": [{gpm_max, pipe_mm}],
          "trap_size_mm_per_fixture": {fixture: {...}},
          "trap_notes": {...},
          "vent_stack_size_by_dfu": [{dfu_max, max_length_m, vent_mm}],
          "vent_rules": {...},
          "gpm_to_lpm": float,
      },
      "plumbing_pre_calc": {...},
      "cost_bands": {hvac, electrical, plumbing},
      "city_price_index": float,
    }
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import mep as mep_kb  # used for math constants + legacy fallback
from app.repositories.pricing import CityPriceIndexRepository
from app.repositories.standards import StandardsRepository
from app.services.standards import mep_sizing


def _strip_prefix(slug: str, prefix: str) -> str:
    return slug[len(prefix):] if slug.startswith(prefix) else slug


# ─────────────────────────────────────────────────────────────────────
# Helpers — list-active under category=mep, filter by slug prefix
# ─────────────────────────────────────────────────────────────────────


async def _list_mep(
    session: AsyncSession,
    *,
    subcategory: str | None = None,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    repo = StandardsRepository(session)
    return await repo.list_active(
        category="mep",
        subcategory=subcategory,
        jurisdiction=jurisdiction,
    )


async def _resolve_one(
    session: AsyncSession,
    *,
    slug: str,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    repo = StandardsRepository(session)
    row = await repo.resolve(slug=slug, category="mep", jurisdiction=jurisdiction)
    return (row or {}).get("data") or {}


# ─────────────────────────────────────────────────────────────────────
# HVAC table aggregators
# ─────────────────────────────────────────────────────────────────────


async def _ach_table(session: AsyncSession, *, jurisdiction: str) -> dict[str, float]:
    rows = await _list_mep(session, subcategory="hvac", jurisdiction=jurisdiction)
    out: dict[str, float] = {}
    prefix = "mep_hvac_ach_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        data = r.get("data") or {}
        ach = data.get("air_changes_per_hour")
        if ach is None:
            continue
        out[slug[len(prefix):]] = float(ach)
    return out


async def _cfm_per_person_table(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, int]:
    rows = await _list_mep(session, subcategory="hvac", jurisdiction=jurisdiction)
    out: dict[str, int] = {}
    prefix = "mep_hvac_cfm_per_person_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        cfm = (r.get("data") or {}).get("cfm_per_person")
        if cfm is None:
            continue
        out[slug[len(prefix):]] = int(cfm)
    return out


async def _cooling_load_table(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, float]:
    rows = await _list_mep(session, subcategory="hvac", jurisdiction=jurisdiction)
    out: dict[str, float] = {}
    prefix = "mep_hvac_cooling_load_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        tr = (r.get("data") or {}).get("tr_per_m2")
        if tr is None:
            continue
        out[slug[len(prefix):]] = float(tr)
    return out


async def _duct_velocity_table(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, list[float]]:
    rows = await _list_mep(session, subcategory="hvac", jurisdiction=jurisdiction)
    out: dict[str, list[float]] = {}
    prefix = "mep_hvac_duct_velocity_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        band = (r.get("data") or {}).get("velocity_m_s_band")
        if not band:
            continue
        out[slug[len(prefix):]] = [float(band[0]), float(band[1])]
    return out


async def _register_cfm_rating(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, int]:
    rows = await _list_mep(session, subcategory="hvac", jurisdiction=jurisdiction)
    out: dict[str, int] = {}
    prefix = "mep_hvac_register_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        rating = (r.get("data") or {}).get("cfm_rating")
        if rating is None:
            continue
        out[slug[len(prefix):]] = int(rating)
    return out


async def _equipment_band_tr(
    session: AsyncSession, *, jurisdiction: str
) -> list[dict[str, Any]]:
    data = await _resolve_one(
        session, slug="mep_hvac_equipment_bands", jurisdiction=jurisdiction
    )
    return [
        {"capacity_tr": e.get("capacity_tr"), "label": e.get("label")}
        for e in (data.get("entries") or [])
    ]


async def _duct_round_chart(
    session: AsyncSession, *, jurisdiction: str
) -> list[dict[str, Any]]:
    data = await _resolve_one(
        session,
        slug="mep_hvac_duct_round_diameter_table",
        jurisdiction=jurisdiction,
    )
    return [
        {"cfm_max": e.get("max_cfm"), "diameter_mm": e.get("diameter_mm")}
        for e in (data.get("entries") or [])
    ]


# ─────────────────────────────────────────────────────────────────────
# Electrical table aggregators
# ─────────────────────────────────────────────────────────────────────


async def _lux_levels(session: AsyncSession, *, jurisdiction: str) -> dict[str, int]:
    rows = await _list_mep(session, subcategory="electrical", jurisdiction=jurisdiction)
    out: dict[str, int] = {}
    prefix = "mep_elec_lux_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        lux = (r.get("data") or {}).get("lux_target")
        if lux is None:
            continue
        out[slug[len(prefix):]] = int(lux)
    return out


async def _circuit_load_table(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, int]:
    rows = await _list_mep(session, subcategory="electrical", jurisdiction=jurisdiction)
    out: dict[str, int] = {}
    prefix = "mep_elec_circuit_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        load = (r.get("data") or {}).get("max_load_w")
        if load is None:
            continue
        out[slug[len(prefix):]] = int(load)
    return out


async def _power_density_table(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, int]:
    rows = await _list_mep(session, subcategory="electrical", jurisdiction=jurisdiction)
    out: dict[str, int] = {}
    prefix = "mep_elec_power_density_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        w = (r.get("data") or {}).get("watts_per_m2")
        if w is None:
            continue
        out[slug[len(prefix):]] = int(w)
    return out


async def _fixture_catalogue(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, Any]]:
    rows = await _list_mep(session, subcategory="electrical", jurisdiction=jurisdiction)
    out: dict[str, dict[str, Any]] = {}
    prefix = "mep_elec_fixture_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        data = dict(r.get("data") or {})
        data.pop("fixture_key", None)
        out[slug[len(prefix):]] = data
    return out


async def _outlet_catalogue(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, Any]]:
    rows = await _list_mep(session, subcategory="electrical", jurisdiction=jurisdiction)
    out: dict[str, dict[str, Any]] = {}
    prefix = "mep_elec_outlet_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        data = dict(r.get("data") or {})
        data.pop("outlet_key", None)
        out[slug[len(prefix):]] = data
    return out


async def _task_lighting_recipe(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, list[dict[str, Any]]]:
    rows = await _list_mep(session, subcategory="electrical", jurisdiction=jurisdiction)
    out: dict[str, list[dict[str, Any]]] = {}
    prefix = "mep_elec_task_lighting_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        zones = (r.get("data") or {}).get("zones") or []
        out[slug[len(prefix):]] = [dict(z) for z in zones]
    return out


async def _layout_rules(session: AsyncSession, *, jurisdiction: str) -> dict[str, Any]:
    return await _resolve_one(
        session, slug="mep_elec_layout_rules", jurisdiction=jurisdiction
    )


# ─────────────────────────────────────────────────────────────────────
# Plumbing table aggregators
# ─────────────────────────────────────────────────────────────────────


async def _dfu_per_fixture(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, int]:
    rows = await _list_mep(session, subcategory="plumbing", jurisdiction=jurisdiction)
    out: dict[str, int] = {}
    prefix = "mep_plumb_dfu_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        dfu = (r.get("data") or {}).get("dfu")
        if dfu is None:
            continue
        out[slug[len(prefix):]] = int(dfu)
    return out


async def _wsfu_per_fixture(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, float]]:
    rows = await _list_mep(session, subcategory="plumbing", jurisdiction=jurisdiction)
    out: dict[str, dict[str, float]] = {}
    prefix = "mep_plumb_wsfu_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        data = dict(r.get("data") or {})
        data.pop("fixture", None)
        out[slug[len(prefix):]] = data
    return out


async def _trap_per_fixture(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, dict[str, Any]]:
    rows = await _list_mep(session, subcategory="plumbing", jurisdiction=jurisdiction)
    out: dict[str, dict[str, Any]] = {}
    prefix = "mep_plumb_trap_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        data = dict(r.get("data") or {})
        data.pop("fixture", None)
        out[slug[len(prefix):]] = data
    return out


async def _water_demand(
    session: AsyncSession, *, jurisdiction: str
) -> dict[str, list[float]]:
    rows = await _list_mep(session, subcategory="plumbing", jurisdiction=jurisdiction)
    out: dict[str, list[float]] = {}
    prefix = "mep_plumb_water_demand_"
    for r in rows:
        slug = r.get("slug") or ""
        if not slug.startswith(prefix):
            continue
        band = (r.get("data") or {}).get("litres_per_day_band")
        if not band:
            continue
        out[slug[len(prefix):]] = [float(band[0]), float(band[1])]
    return out


async def _pipe_size_chart(
    session: AsyncSession, *, jurisdiction: str
) -> list[dict[str, Any]]:
    data = await _resolve_one(
        session, slug="mep_plumb_pipe_by_dfu_table", jurisdiction=jurisdiction
    )
    return [
        {"dfu_max": e.get("max_dfu"), "pipe_mm": e.get("pipe_size_mm")}
        for e in (data.get("entries") or [])
    ]


async def _supply_pipe_chart(
    session: AsyncSession, *, jurisdiction: str
) -> list[dict[str, Any]]:
    data = await _resolve_one(
        session, slug="mep_plumb_supply_pipe_by_gpm_table", jurisdiction=jurisdiction
    )
    return [
        {"gpm_max": e.get("max_gpm"), "pipe_mm": e.get("pipe_size_mm")}
        for e in (data.get("entries") or [])
    ]


async def _hunters_curve(
    session: AsyncSession, *, jurisdiction: str
) -> list[dict[str, Any]]:
    data = await _resolve_one(
        session, slug="mep_plumb_hunters_curve_flush_tank", jurisdiction=jurisdiction
    )
    return [
        {"wsfu": e.get("wsfu"), "gpm": e.get("gpm")}
        for e in (data.get("entries") or [])
    ]


async def _vent_stack_chart(
    session: AsyncSession, *, jurisdiction: str
) -> list[dict[str, Any]]:
    data = await _resolve_one(
        session, slug="mep_plumb_vent_stack_size_table", jurisdiction=jurisdiction
    )
    return [
        {
            "dfu_max": e.get("max_dfu_on_stack"),
            "max_length_m": e.get("max_developed_length_m"),
            "vent_mm": e.get("vent_size_mm"),
        }
        for e in (data.get("entries") or [])
    ]


async def _slope_rules(session: AsyncSession, *, jurisdiction: str) -> dict[str, Any]:
    return await _resolve_one(
        session, slug="mep_plumb_slope_rules", jurisdiction=jurisdiction
    )


async def _vent_rules(session: AsyncSession, *, jurisdiction: str) -> dict[str, Any]:
    return await _resolve_one(
        session, slug="mep_plumb_vent_rules", jurisdiction=jurisdiction
    )


# ─────────────────────────────────────────────────────────────────────
# Public — full pack
# ─────────────────────────────────────────────────────────────────────


def _normalise(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_").replace("-", "_")


async def load_mep_spec_pack(
    session: AsyncSession,
    *,
    room_use_type: str,
    length_m: float,
    width_m: float,
    height_m: float,
    fixtures: list[str] | None = None,
    city: Optional[str] = None,
    hvac_system: Optional[str] = None,
    electrical_system: Optional[str] = None,
    plumbing_system: Optional[str] = None,
    cooling_use: Optional[str] = None,
    power_use: Optional[str] = None,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Return the full MEP-KB dict the spec-sheet builder needs.

    Pre-computes every BRD sizing the LLM will cite plus loads the 13
    reference tables. Pure DB reads — no Python-literal authority.
    """
    use = _normalise(room_use_type)
    area = float(length_m) * float(width_m)
    volume = area * float(height_m)
    fixtures_in = [_normalise(f) for f in (fixtures or [])]

    # ── HVAC pre-calc ─────────────────────────────────────────────────
    hvac_calc = await mep_sizing.hvac_cfm(
        session, room_volume_m3=volume, use_type=use, jurisdiction=jurisdiction
    )
    cooling = await mep_sizing.cooling_tr(
        session,
        area_m2=area,
        use_type=cooling_use or use,
        jurisdiction=jurisdiction,
    )
    equipment_pick = (
        await mep_sizing.equipment_shortlist(
            session,
            tonnage_required=float(cooling.get("tonnage") or 0),
            jurisdiction=jurisdiction,
        )
        if cooling.get("tonnage") is not None
        else {}
    )
    # equipment_capacity is pure-math (BTU/TR + KW/TR constants) — left
    # on legacy literal since these are physical constants.
    equipment = (
        mep_kb.equipment_capacity(cooling.get("tonnage") or 0)
        if cooling.get("tonnage") is not None
        else {}
    )
    cfm = hvac_calc.get("cfm_total") if isinstance(hvac_calc, dict) else None
    duct_round = (
        await mep_sizing.duct_round_diameter(
            session, cfm=float(cfm), jurisdiction=jurisdiction
        )
        if cfm
        else {}
    )
    # duct_rectangular_for_cfm is geometry-math (width × height for a
    # given velocity + aspect) — left on legacy literal.
    duct_rect = (
        mep_kb.duct_rectangular_for_cfm(cfm, velocity_m_s=5.0, aspect_ratio=2.0)
        if cfm
        else {}
    )

    # ── Electrical pre-calc ───────────────────────────────────────────
    lighting = (
        await mep_sizing.lighting_circuits(
            session,
            area_m2=area,
            use=power_use or use,
            jurisdiction=jurisdiction,
        )
        if area
        else {}
    )
    ambient_lux_target = None
    task_lux_target = None
    lux_levels = await _lux_levels(session, jurisdiction=jurisdiction)
    ambient_lux_target = lux_levels.get(f"{use}_general") or 200
    task_lux_target = lux_levels.get(f"{use}_task") or ambient_lux_target
    ambient_pick = (
        await mep_sizing.ambient_fixture_count(
            session,
            area_m2=area,
            lux_target=float(ambient_lux_target),
            fixture_key="led_downlight_18w",
            jurisdiction=jurisdiction,
        )
        if area
        else {}
    )
    perimeter = 2 * (float(length_m) + float(width_m))
    outlet_pick = (
        await mep_sizing.outlet_estimate(
            session,
            room_type=use,
            perimeter_m=perimeter,
            jurisdiction=jurisdiction,
        )
        if perimeter
        else {}
    )
    task_recipes = await _task_lighting_recipe(session, jurisdiction=jurisdiction)
    task_recipe_for_use = task_recipes.get(use) or []

    # ── Plumbing pre-calc ─────────────────────────────────────────────
    dfu_map = await _dfu_per_fixture(session, jurisdiction=jurisdiction)
    wsfu_map = await _wsfu_per_fixture(session, jurisdiction=jurisdiction)
    valid_fixtures = [f for f in fixtures_in if f in wsfu_map]
    supply_summary = (
        await mep_sizing.fixture_water_supply_summary(
            session, fixtures=valid_fixtures, jurisdiction=jurisdiction
        )
        if valid_fixtures
        else {}
    )
    total_dfu = sum(dfu_map.get(f, 0) for f in valid_fixtures)
    drain_pick = (
        await mep_sizing.pipe_size_for_dfu(
            session, total_dfu=total_dfu, jurisdiction=jurisdiction
        )
        if total_dfu
        else {}
    )
    vent_pick = (
        await mep_sizing.vent_size_for_dfu(
            session,
            total_dfu=total_dfu,
            developed_length_m=15.0,
            jurisdiction=jurisdiction,
        )
        if total_dfu
        else {}
    )
    trap_map = await _trap_per_fixture(session, jurisdiction=jurisdiction)
    trap_picks = [
        {"fixture": f, **(trap_map.get(f) or {})} for f in valid_fixtures
    ]

    # ── Reference tables ──────────────────────────────────────────────
    ach_table = await _ach_table(session, jurisdiction=jurisdiction)
    cfm_per_person = await _cfm_per_person_table(session, jurisdiction=jurisdiction)
    cooling_load = await _cooling_load_table(session, jurisdiction=jurisdiction)
    duct_velocity = await _duct_velocity_table(session, jurisdiction=jurisdiction)
    register_rating = await _register_cfm_rating(session, jurisdiction=jurisdiction)
    equipment_band = await _equipment_band_tr(session, jurisdiction=jurisdiction)
    duct_round_chart = await _duct_round_chart(session, jurisdiction=jurisdiction)

    circuit_load = await _circuit_load_table(session, jurisdiction=jurisdiction)
    power_density = await _power_density_table(session, jurisdiction=jurisdiction)
    fixture_cat = await _fixture_catalogue(session, jurisdiction=jurisdiction)
    outlet_cat = await _outlet_catalogue(session, jurisdiction=jurisdiction)
    layout_rules = await _layout_rules(session, jurisdiction=jurisdiction)

    water_demand = await _water_demand(session, jurisdiction=jurisdiction)
    pipe_size_chart = await _pipe_size_chart(session, jurisdiction=jurisdiction)
    supply_pipe_chart = await _supply_pipe_chart(session, jurisdiction=jurisdiction)
    hunters_curve = await _hunters_curve(session, jurisdiction=jurisdiction)
    vent_stack_chart = await _vent_stack_chart(session, jurisdiction=jurisdiction)
    slope_rules = await _slope_rules(session, jurisdiction=jurisdiction)
    vent_rules = await _vent_rules(session, jurisdiction=jurisdiction)

    # ── Cost bands (3 system_cost picks) ──────────────────────────────
    cost_bands: dict[str, dict[str, Any]] = {}
    if hvac_system:
        cost_bands["hvac"] = await mep_sizing.system_cost_estimate(
            session, system_key=hvac_system, area_m2=area, jurisdiction=jurisdiction
        )
    if electrical_system:
        cost_bands["electrical"] = await mep_sizing.system_cost_estimate(
            session,
            system_key=electrical_system,
            area_m2=area,
            jurisdiction=jurisdiction,
        )
    if plumbing_system:
        cost_bands["plumbing"] = await mep_sizing.system_cost_estimate(
            session,
            system_key=plumbing_system,
            area_m2=area,
            jurisdiction=jurisdiction,
        )

    # ── City index ────────────────────────────────────────────────────
    city_index: float = 1.0
    if city:
        repo = CityPriceIndexRepository(session)
        row = await repo.resolve(city)
        if row:
            try:
                city_index = float(row["index_multiplier"])
            except (TypeError, ValueError, KeyError):
                city_index = 1.0

    return {
        "hvac_brd": {
            "ach_table": ach_table,
            "cfm_per_person_table": cfm_per_person,
            "cooling_load_tr_per_m2": cooling_load,
            "duct_velocity_m_s": duct_velocity,
            "btu_per_tr": mep_kb.BTU_PER_TR,
            "kw_per_tr": mep_kb.KW_PER_TR,
            "equipment_band_tr": equipment_band,
            "duct_round_chart_mm_by_cfm": duct_round_chart,
            "register_cfm_rating": register_rating,
        },
        "hvac_pre_calc": {
            "ach_target": hvac_calc.get("ach") if isinstance(hvac_calc, dict) else None,
            "cfm_total": cfm,
            "cooling_tonnage": cooling.get("tonnage"),
            "btu_per_hr": equipment.get("btu_per_hr"),
            "kw_thermal": equipment.get("kw_thermal"),
            "equipment_pick": equipment_pick,
            "duct_round_diameter_mm": duct_round.get("diameter_mm"),
            "duct_rectangular_mm": {
                "width": duct_rect.get("width_mm"),
                "height": duct_rect.get("height_mm"),
                "velocity_m_s": duct_rect.get("velocity_m_s"),
            },
            "cooling_use_mapped": cooling_use or use,
        },
        "electrical_brd": {
            "lux_levels": lux_levels,
            "circuit_load_w": circuit_load,
            "power_density_w_per_m2": power_density,
            "fixture_catalogue": fixture_cat,
            "outlet_catalogue": outlet_cat,
            "outlet_count_rule": dict(mep_kb.OUTLET_COUNT_RULE),
            "task_lighting_recipe": task_recipes,
            "lighting_layout_rules": layout_rules,
        },
        "electrical_pre_calc": {
            "power_use_mapped": power_use or use,
            "ambient_lux_target": ambient_lux_target,
            "task_lux_target": task_lux_target,
            "power_density_w_per_m2": lighting.get("density_w_m2"),
            "total_lighting_load_w": lighting.get("total_load_w"),
            "lighting_circuits_min": lighting.get("lighting_circuits"),
            "ambient_fixture_pick": ambient_pick,
            "outlet_pick": outlet_pick,
            "task_lighting_recipe_for_use": task_recipe_for_use,
            "perimeter_m": round(perimeter, 2),
        },
        "plumbing_brd": {
            "dfu_per_fixture": dfu_map,
            "pipe_size_mm_by_dfu": pipe_size_chart,
            "slope_per_metre": dict(mep_kb.SLOPE_PER_METRE),
            "slope_requirement": slope_rules,
            "water_demand_lpd": water_demand,
            "wsfu_per_fixture": wsfu_map,
            "hunters_curve_flush_tank": hunters_curve,
            "supply_pipe_size_mm_by_gpm": supply_pipe_chart,
            "trap_size_mm_per_fixture": trap_map,
            "trap_notes": dict(mep_kb.TRAP_NOTES),
            "vent_stack_size_by_dfu": vent_stack_chart,
            "vent_rules": vent_rules,
            "gpm_to_lpm": mep_kb.GPM_TO_LPM,
        },
        "plumbing_pre_calc": {
            "fixtures_normalised": valid_fixtures,
            "supply_summary": supply_summary,
            "total_dfu": total_dfu,
            "drain_pipe_pick": drain_pick,
            "vent_pick": vent_pick,
            "trap_picks": trap_picks,
        },
        "cost_bands": cost_bands,
        "city_price_index": city_index,
    }
