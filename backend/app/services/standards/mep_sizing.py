"""Async DB-backed MEP sizing helpers (Stage 3C).

Mirrors the sync helpers in :mod:`app.knowledge.mep` (``hvac_cfm``,
``cooling_tr``, ``equipment_shortlist``, ``duct_round_diameter``,
``lighting_circuits``, ``ambient_fixture_count``, ``outlet_estimate``,
``pipe_size_for_dfu``, ``water_supply_demand_gpm``,
``vent_size_for_dfu``, ``system_cost_estimate``) but reads every
constant from the versioned ``building_standards`` table.

These wrappers preserve the legacy return shape so:
  - the MEP-spec service can adopt them with one-line replacements,
  - Stage 4 can wrap them as agent tools using the same patterns as
    ``estimate_project_cost`` (Stage 2).

Physics constants stay as module-level literals — they're not market
or jurisdiction volatile (e.g. ``BTU_PER_TR == 12_000``).
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.standards import StandardsRepository

# ─────────────────────────────────────────────────────────────────────
# Physics constants — stay in code (immutable by definition)
# ─────────────────────────────────────────────────────────────────────

BTU_PER_TR: int = 12_000          # 1 ton of refrigeration
KW_PER_TR: float = 3.517           # ≈ 3.517 kW thermal
GPM_TO_LPM: float = 3.78541        # 1 US gallon = 3.78541 litres
M3_TO_FT3: float = 35.3147         # m³ → ft³

DEFAULT_LIGHT_LOSS_FACTOR: float = 0.8
DEFAULT_MAINTENANCE_FACTOR: float = 0.7


# ─────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────


async def _get_data(
    session: AsyncSession,
    *,
    slug: str,
    jurisdiction: str = "india_nbc",
) -> Optional[dict[str, Any]]:
    """Resolve a single MEP standard's ``data`` payload, or None."""
    repo = StandardsRepository(session)
    row = await repo.resolve(
        slug=slug, category="mep", jurisdiction=jurisdiction
    )
    return row["data"] if row else None


async def _get_table_entries(
    session: AsyncSession,
    *,
    slug: str,
    jurisdiction: str = "india_nbc",
) -> list[dict[str, Any]]:
    """Fetch a table-style standard's ``data["entries"]`` list."""
    data = await _get_data(session, slug=slug, jurisdiction=jurisdiction)
    if not data:
        return []
    entries = data.get("entries") or []
    return list(entries)


# ─────────────────────────────────────────────────────────────────────
# HVAC
# ─────────────────────────────────────────────────────────────────────


async def hvac_cfm(
    session: AsyncSession,
    *,
    room_volume_m3: float,
    use_type: str,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Total fresh-air CFM required for a room.

    Mirrors :func:`app.knowledge.mep.hvac_cfm`.
    """
    data = await _get_data(
        session, slug=f"mep_hvac_ach_{use_type}", jurisdiction=jurisdiction
    )
    if not data:
        return {"error": f"Unknown use_type {use_type!r}"}
    ach = float(data["air_changes_per_hour"])
    cfm = (room_volume_m3 * M3_TO_FT3 * ach) / 60.0
    return {"ach": ach, "cfm_total": round(cfm, 1), "use_type": use_type}


async def cooling_tr(
    session: AsyncSession,
    *,
    area_m2: float,
    use_type: str,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Cooling load (tonnage) for an area in tropical India."""
    data = await _get_data(
        session, slug=f"mep_hvac_cooling_load_{use_type}", jurisdiction=jurisdiction
    )
    if not data:
        return {"error": f"No cooling factor for {use_type!r}"}
    tr = area_m2 * float(data["tr_per_m2"])
    return {"tonnage": round(tr, 2), "use_type": use_type}


def equipment_capacity(tonnage: float) -> dict[str, Any]:
    """Tonnage → BTU/hr and kW thermal. Pure physics, no DB read."""
    return {
        "tonnage": round(float(tonnage), 2),
        "btu_per_hr": round(float(tonnage) * BTU_PER_TR, 0),
        "kw_thermal": round(float(tonnage) * KW_PER_TR, 2),
    }


async def equipment_shortlist(
    session: AsyncSession,
    *,
    tonnage_required: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Pick the smallest standard unit that meets the load.

    Reads the ``mep_hvac_equipment_bands`` table-row.
    """
    entries = await _get_table_entries(
        session, slug="mep_hvac_equipment_bands", jurisdiction=jurisdiction
    )
    for entry in entries:
        cap = float(entry["capacity_tr"])
        if tonnage_required <= cap + 1e-6:
            return {
                "required_tr": round(tonnage_required, 2),
                "selected_tr": cap,
                "type": entry["label"],
            }
    if not entries:
        return {"error": "No equipment band table seeded"}
    last = entries[-1]
    return {
        "required_tr": round(tonnage_required, 2),
        "selected_tr": float(last["capacity_tr"]),
        "type": last["label"],
        "note": "Exceeds top band — split into multiple units or step up to chilled water.",
    }


async def duct_round_diameter(
    session: AsyncSession,
    *,
    cfm: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    entries = await _get_table_entries(
        session, slug="mep_hvac_duct_round_diameter_table", jurisdiction=jurisdiction
    )
    for entry in entries:
        if cfm <= float(entry["max_cfm"]):
            return {"cfm": round(cfm, 1), "diameter_mm": int(entry["diameter_mm"])}
    if not entries:
        return {"error": "No duct sizing table seeded"}
    last = entries[-1]
    return {
        "cfm": round(cfm, 1),
        "diameter_mm": int(last["diameter_mm"]),
        "note": "Exceeds chart — split into parallel runs or step up to rectangular trunk.",
    }


# ─────────────────────────────────────────────────────────────────────
# Electrical
# ─────────────────────────────────────────────────────────────────────


async def lighting_circuits(
    session: AsyncSession,
    *,
    area_m2: float,
    use: str = "residential",
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    density_data = await _get_data(
        session, slug=f"mep_elec_power_density_{use}", jurisdiction=jurisdiction
    )
    density = int(density_data["watts_per_m2"]) if density_data else 40

    circuit_data = await _get_data(
        session,
        slug="mep_elec_circuit_lighting_circuit_max",
        jurisdiction=jurisdiction,
    )
    max_per_circuit = int(circuit_data["max_load_w"]) if circuit_data else 1500

    total_w = area_m2 * density
    n = max(1, int(total_w // max_per_circuit) + 1)
    return {
        "total_load_w": int(total_w),
        "lighting_circuits": n,
        "density_w_m2": density,
    }


async def ambient_fixture_count(
    session: AsyncSession,
    *,
    area_m2: float,
    lux_target: float,
    fixture_key: str = "led_downlight_18w",
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Count luminaires needed to hit a lux target. LLF / MF folded in."""
    spec = await _get_data(
        session,
        slug=f"mep_elec_fixture_{fixture_key}",
        jurisdiction=jurisdiction,
    )
    if not spec or area_m2 <= 0 or lux_target <= 0:
        return {"error": "bad inputs", "fixture_key": fixture_key}

    lumens = float(spec["lumens"])
    watts = float(spec["watts"])
    effective = lumens * DEFAULT_LIGHT_LOSS_FACTOR * DEFAULT_MAINTENANCE_FACTOR
    required_lumens = lux_target * area_m2
    n = max(1, int(-(-required_lumens // effective)))
    return {
        "fixture_key": fixture_key,
        "lumens_per_fixture": int(lumens),
        "watts_per_fixture": int(watts),
        "count": n,
        "total_watts": int(n * watts),
        "total_lumens": int(n * lumens),
        "lux_design": round((n * effective) / area_m2, 0),
    }


async def outlet_estimate(
    session: AsyncSession,
    *,
    room_type: str,
    perimeter_m: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    rule = await _get_data(
        session,
        slug=f"mep_elec_outlet_rule_{room_type}",
        jurisdiction=jurisdiction,
    )
    if not rule:
        # fall back to office_general
        rule = await _get_data(
            session,
            slug="mep_elec_outlet_rule_office_general",
            jurisdiction=jurisdiction,
        )
    if not rule:
        return {"error": "No outlet rule seeded"}

    n_general = max(
        int(rule["min_general"]),
        int(round(perimeter_m * float(rule["general_per_m_wall"]))),
    )
    return {
        "room_type": room_type,
        "perimeter_m": round(perimeter_m, 2),
        "general_outlets": n_general,
        "task_zones": int(rule["task_zones"]),
    }


# ─────────────────────────────────────────────────────────────────────
# Plumbing
# ─────────────────────────────────────────────────────────────────────


async def pipe_size_for_dfu(
    session: AsyncSession,
    *,
    total_dfu: int,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    entries = await _get_table_entries(
        session, slug="mep_plumb_pipe_by_dfu_table", jurisdiction=jurisdiction
    )
    for entry in entries:
        if total_dfu <= int(entry["max_dfu"]):
            return {"total_dfu": total_dfu, "pipe_size_mm": int(entry["pipe_size_mm"])}
    if not entries:
        return {"error": "No pipe-size table seeded"}
    last = entries[-1]
    return {
        "total_dfu": total_dfu,
        "pipe_size_mm": int(last["pipe_size_mm"]),
        "note": "exceeds table; size up",
    }


async def water_supply_demand_gpm(
    session: AsyncSession,
    *,
    total_wsfu: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """WSFU → probable demand GPM via Hunter's curve (flush-tank)."""
    if total_wsfu <= 0:
        return {"total_wsfu": 0, "demand_gpm": 0.0, "demand_lpm": 0.0}
    entries = await _get_table_entries(
        session,
        slug="mep_plumb_hunters_curve_flush_tank",
        jurisdiction=jurisdiction,
    )
    if not entries:
        return {"error": "No Hunter's curve seeded"}

    if total_wsfu <= float(entries[0]["wsfu"]):
        gpm = float(entries[0]["gpm"])
    else:
        gpm = float(entries[-1]["gpm"])
        for lo, hi in zip(entries, entries[1:]):
            lo_w, lo_g = float(lo["wsfu"]), float(lo["gpm"])
            hi_w, hi_g = float(hi["wsfu"]), float(hi["gpm"])
            if total_wsfu <= hi_w:
                gpm = lo_g + (hi_g - lo_g) * (total_wsfu - lo_w) / (hi_w - lo_w)
                break

    return {
        "total_wsfu": round(total_wsfu, 2),
        "demand_gpm": round(gpm, 2),
        "demand_lpm": round(gpm * GPM_TO_LPM, 2),
        "curve": "hunter_flush_tank",
    }


async def supply_pipe_size_for_gpm(
    session: AsyncSession,
    *,
    gpm: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    entries = await _get_table_entries(
        session,
        slug="mep_plumb_supply_pipe_by_gpm_table",
        jurisdiction=jurisdiction,
    )
    for entry in entries:
        if gpm <= float(entry["max_gpm"]):
            return {"gpm": round(gpm, 2), "pipe_size_mm": int(entry["pipe_size_mm"])}
    if not entries:
        return {"error": "No supply-pipe table seeded"}
    last = entries[-1]
    return {
        "gpm": round(gpm, 2),
        "pipe_size_mm": int(last["pipe_size_mm"]),
        "note": "exceeds table; size up to 100 mm or split runs",
    }


async def vent_size_for_dfu(
    session: AsyncSession,
    *,
    total_dfu: int,
    developed_length_m: float = 0.0,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    entries = await _get_table_entries(
        session, slug="mep_plumb_vent_stack_size_table", jurisdiction=jurisdiction
    )
    for entry in entries:
        cap = int(entry["max_dfu_on_stack"])
        max_len = int(entry["max_developed_length_m"])
        if total_dfu <= cap and developed_length_m <= max_len:
            return {
                "total_dfu": total_dfu,
                "developed_length_m": round(developed_length_m, 1),
                "vent_size_mm": int(entry["vent_size_mm"]),
                "max_length_m_for_size": max_len,
            }
    if not entries:
        return {"error": "No vent-size table seeded"}
    last = entries[-1]
    return {
        "total_dfu": total_dfu,
        "developed_length_m": round(developed_length_m, 1),
        "vent_size_mm": int(last["vent_size_mm"]),
        "max_length_m_for_size": int(last["max_developed_length_m"]),
        "note": "exceeds table; step up to 150 mm or shorten developed length",
    }


async def fixture_water_supply_summary(
    session: AsyncSession,
    *,
    fixtures: list[str],
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Roll up WSFU + GPM demand from a fixture list."""
    cold = hot = total = 0.0
    rows: list[dict[str, Any]] = []
    for f in fixtures:
        spec = await _get_data(
            session,
            slug=f"mep_plumb_wsfu_{f}",
            jurisdiction=jurisdiction,
        )
        if not spec:
            continue
        cold += float(spec["cold"])
        hot += float(spec["hot"])
        total += float(spec["total"])
        rows.append({"fixture": f, **{k: spec[k] for k in ("cold", "hot", "total")}})
    demand = await water_supply_demand_gpm(
        session, total_wsfu=total, jurisdiction=jurisdiction
    )
    main_size = await supply_pipe_size_for_gpm(
        session,
        gpm=float(demand.get("demand_gpm", 0.0)),
        jurisdiction=jurisdiction,
    )
    return {
        "fixtures": rows,
        "wsfu_cold": round(cold, 2),
        "wsfu_hot": round(hot, 2),
        "wsfu_total": round(total, 2),
        "demand_gpm": demand.get("demand_gpm", 0.0),
        "demand_lpm": demand.get("demand_lpm", 0.0),
        "supply_main_pipe_size_mm": main_size.get("pipe_size_mm"),
    }


# ─────────────────────────────────────────────────────────────────────
# System cost
# ─────────────────────────────────────────────────────────────────────


async def system_cost_estimate(
    session: AsyncSession,
    *,
    system_key: str,
    area_m2: float,
    jurisdiction: str = "india_nbc",
) -> dict[str, Any]:
    """Rough order-of-magnitude MEP system cost for an area."""
    data = await _get_data(
        session,
        slug=f"mep_system_cost_{system_key}",
        jurisdiction=jurisdiction,
    )
    if not data:
        return {"error": f"No cost band for system {system_key!r}"}
    lo = float(data["rate_inr_per_m2_low"])
    hi = float(data["rate_inr_per_m2_high"])
    return {
        "system": system_key,
        "area_m2": area_m2,
        "rate_inr_m2": {"low": lo, "high": hi},
        "total_inr": {"low": round(lo * area_m2, 0), "high": round(hi * area_m2, 0)},
    }
