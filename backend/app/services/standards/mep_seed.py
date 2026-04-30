"""Stage 3C — MEP seed builder.

Translates :mod:`app.knowledge.mep` into ``building_standards`` rows
(``category='mep'``). The schema is already in place from Stage 3B —
this stage only writes data.

Slug naming convention
----------------------
- ``mep_hvac_<rule>_<key>``        — HVAC scalar lookups (ACH, CFM, …)
- ``mep_hvac_<rule>_table``        — HVAC sequence tables
- ``mep_elec_<rule>_<key>``        — Electrical scalars + catalogues
- ``mep_plumb_<rule>_<fixture>``   — Plumbing per-fixture rules
- ``mep_plumb_<rule>_table``       — Plumbing sequence tables
- ``mep_system_cost_<system>``     — Per-m² system cost bands

Subcategories: ``hvac`` | ``electrical`` | ``plumbing`` | ``system_cost``.

What stays in code
------------------
- Physics constants (``BTU_PER_TR``, ``KW_PER_TR``, ``GPM_TO_LPM``).
- Helper formulas (``hvac_cfm``, ``cooling_tr``, etc) — Stage 3C
  ships async DB-backed equivalents in
  :mod:`app.services.standards.mep_sizing`.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from app.knowledge import mep as mep_kb


def _new_id() -> str:
    return uuid4().hex


def _scalar_row(
    slug: str,
    *,
    subcategory: str,
    display_name: str,
    data: dict[str, Any],
    source_section: str | None = None,
    notes: str | None = None,
    source_tag: str = "seed:mep",
) -> dict[str, Any]:
    return {
        "id": _new_id(),
        "slug": slug,
        "category": "mep",
        "jurisdiction": "india_nbc",
        "subcategory": subcategory,
        "display_name": display_name,
        "notes": notes,
        "data": data,
        "source_section": source_section,
        "source_doc": "BRD-Phase-1",
        "source": source_tag,
    }


# ─────────────────────────────────────────────────────────────────────
# HVAC
# ─────────────────────────────────────────────────────────────────────


def _hvac_ach_rows() -> list[dict[str, Any]]:
    """One row per (room_type, ACH) entry from AIR_CHANGES_PER_HOUR."""
    return [
        _scalar_row(
            f"mep_hvac_ach_{room_type}",
            subcategory="hvac",
            display_name=f"HVAC — Air changes per hour, {room_type.replace('_', ' ')}",
            data={
                "room_type": room_type,
                "air_changes_per_hour": float(value),
            },
            source_section="ASHRAE 62.1 / NBC Part 9",
            source_tag="seed:mep.AIR_CHANGES_PER_HOUR",
        )
        for room_type, value in mep_kb.AIR_CHANGES_PER_HOUR.items()
    ]


def _hvac_cfm_per_person_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_hvac_cfm_per_person_{use_type}",
            subcategory="hvac",
            display_name=f"HVAC — CFM per person, {use_type.replace('_', ' ')}",
            data={"use_type": use_type, "cfm_per_person": float(value)},
            source_section="ASHRAE 62.1 (ventilation)",
            source_tag="seed:mep.CFM_PER_PERSON",
        )
        for use_type, value in mep_kb.CFM_PER_PERSON.items()
    ]


def _hvac_cooling_load_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_hvac_cooling_load_{use_type}",
            subcategory="hvac",
            display_name=f"HVAC — Cooling load (TR/m²), {use_type.replace('_', ' ')}",
            data={
                "use_type": use_type,
                "tr_per_m2": float(value),
                # Inverse for prompt ergonomics — easier to read.
                "m2_per_tr_approx": round(1.0 / float(value), 2) if value else None,
            },
            notes="Tropical-India rule of thumb",
            source_section="BRD Layer 1B — HVAC sizing",
            source_tag="seed:mep.COOLING_LOAD_TR_PER_M2",
        )
        for use_type, value in mep_kb.COOLING_LOAD_TR_PER_M2.items()
    ]


def _hvac_duct_velocity_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_hvac_duct_velocity_{zone}",
            subcategory="hvac",
            display_name=f"HVAC — Duct velocity target, {zone.replace('_', ' ')}",
            data={"zone": zone, "velocity_m_s_band": [float(lo), float(hi)]},
            source_section="ASHRAE / SMACNA duct sizing",
            source_tag="seed:mep.DUCT_VELOCITY_M_S",
        )
        for zone, (lo, hi) in mep_kb.DUCT_VELOCITY_M_S.items()
    ]


def _hvac_equipment_band_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_hvac_equipment_bands",
        subcategory="hvac",
        display_name="HVAC — Standard equipment shortlist by tonnage",
        data={
            "entries": [
                {"capacity_tr": float(cap), "label": label}
                for cap, label in mep_kb.EQUIPMENT_BAND_TR
            ],
        },
        notes="Indian-market standard sizes; pick the smallest unit that meets the load.",
        source_section="BRD Layer 1B — equipment sizing",
        source_tag="seed:mep.EQUIPMENT_BAND_TR",
    )


def _hvac_duct_round_table_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_hvac_duct_round_diameter_table",
        subcategory="hvac",
        display_name="HVAC — Round-duct diameter by CFM",
        data={
            "entries": [
                {"max_cfm": int(cfm), "diameter_mm": int(dia)}
                for cfm, dia in mep_kb.DUCT_ROUND_DIAMETER_MM_BY_CFM
            ],
            "velocity_assumption_m_s": 4.0,
        },
        source_section="ASHRAE duct-sizing chart (≈4 m/s)",
        source_tag="seed:mep.DUCT_ROUND_DIAMETER_MM_BY_CFM",
    )


def _hvac_register_rating_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_hvac_register_{key}",
            subcategory="hvac",
            display_name=f"HVAC — Register rating, {key}",
            data={"register_key": key, "cfm_rating": int(rating)},
            source_section="Light-commercial register selection",
            source_tag="seed:mep.REGISTER_CFM_RATING",
        )
        for key, rating in mep_kb.REGISTER_CFM_RATING.items()
    ]


# ─────────────────────────────────────────────────────────────────────
# Electrical
# ─────────────────────────────────────────────────────────────────────


def _elec_lux_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_elec_lux_{area}",
            subcategory="electrical",
            display_name=f"Electrical — Lux level, {area.replace('_', ' ')}",
            data={"area": area, "lux_target": int(value)},
            source_section="IS 3646 / EN 12464-1 illuminance",
            source_tag="seed:mep.LUX_LEVELS",
        )
        for area, value in mep_kb.LUX_LEVELS.items()
    ]


def _elec_circuit_load_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_elec_circuit_{key}",
            subcategory="electrical",
            display_name=f"Electrical — Circuit load, {key.replace('_', ' ')}",
            data={"circuit_key": key, "max_load_w": int(value)},
            source_section="IS 732 / NEC circuit loading",
            source_tag="seed:mep.CIRCUIT_LOAD_W",
        )
        for key, value in mep_kb.CIRCUIT_LOAD_W.items()
    ]


def _elec_power_density_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_elec_power_density_{use}",
            subcategory="electrical",
            display_name=f"Electrical — Power density, {use.replace('_', ' ')}",
            data={"use_type": use, "watts_per_m2": int(value)},
            source_section="ECBC connected-load benchmarks",
            source_tag="seed:mep.POWER_DENSITY_W_PER_M2",
        )
        for use, value in mep_kb.POWER_DENSITY_W_PER_M2.items()
    ]


def _elec_fixture_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_elec_fixture_{key}",
            subcategory="electrical",
            display_name=f"Electrical — Luminaire, {key.replace('_', ' ')}",
            data={"fixture_key": key, **dict(spec)},
            source_section="LED fixture catalogue (BIS-listed)",
            source_tag="seed:mep.FIXTURE_CATALOGUE",
        )
        for key, spec in mep_kb.FIXTURE_CATALOGUE.items()
    ]


def _elec_outlet_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_elec_outlet_{key}",
            subcategory="electrical",
            display_name=f"Electrical — Outlet, {key.replace('_', ' ')}",
            data={"outlet_key": key, **dict(spec)},
            source_section="IS 1293 wiring devices",
            source_tag="seed:mep.OUTLET_CATALOGUE",
        )
        for key, spec in mep_kb.OUTLET_CATALOGUE.items()
    ]


def _elec_outlet_rule_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_elec_outlet_rule_{room}",
            subcategory="electrical",
            display_name=f"Electrical — Outlet count rule, {room.replace('_', ' ')}",
            data={"room_type": room, **dict(spec)},
            source_section="BIS / IS 732 + studio practice",
            source_tag="seed:mep.OUTLET_COUNT_RULE",
        )
        for room, spec in mep_kb.OUTLET_COUNT_RULE.items()
    ]


def _elec_task_lighting_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_elec_task_lighting_{room}",
            subcategory="electrical",
            display_name=f"Electrical — Task lighting recipe, {room.replace('_', ' ')}",
            data={"room_type": room, "zones": [dict(z) for z in zones]},
            source_section="BRD Layer 1B — task lighting",
            source_tag="seed:mep.TASK_LIGHTING_RECIPE",
        )
        for room, zones in mep_kb.TASK_LIGHTING_RECIPE.items()
    ]


def _elec_layout_rules_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_elec_layout_rules",
        subcategory="electrical",
        display_name="Electrical — Lighting layout rules (S/H ratios, uniformity)",
        data=dict(mep_kb.LIGHTING_LAYOUT_RULES),
        source_section="IES guidance",
        source_tag="seed:mep.LIGHTING_LAYOUT_RULES",
    )


# ─────────────────────────────────────────────────────────────────────
# Plumbing
# ─────────────────────────────────────────────────────────────────────


def _plumb_dfu_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_plumb_dfu_{fixture}",
            subcategory="plumbing",
            display_name=f"Plumbing — DFU, {fixture.replace('_', ' ')}",
            data={"fixture": fixture, "dfu": int(value)},
            source_section="IPC / NBC Part 9 drainage fixture units",
            source_tag="seed:mep.DFU_PER_FIXTURE",
        )
        for fixture, value in mep_kb.DFU_PER_FIXTURE.items()
    ]


def _plumb_wsfu_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_plumb_wsfu_{fixture}",
            subcategory="plumbing",
            display_name=f"Plumbing — WSFU, {fixture.replace('_', ' ')}",
            data={"fixture": fixture, **dict(spec)},
            source_section="IPC 604.3 water supply fixture units",
            source_tag="seed:mep.WSFU_PER_FIXTURE",
        )
        for fixture, spec in mep_kb.WSFU_PER_FIXTURE.items()
    ]


def _plumb_pipe_by_dfu_table_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_plumb_pipe_by_dfu_table",
        subcategory="plumbing",
        display_name="Plumbing — Drain pipe size by DFU",
        data={
            "entries": [
                {"max_dfu": int(dfu), "pipe_size_mm": int(size)}
                for dfu, size in mep_kb.PIPE_SIZE_MM_BY_DFU
            ]
        },
        source_section="IPC / NBC Part 9 drain sizing",
        source_tag="seed:mep.PIPE_SIZE_MM_BY_DFU",
    )


def _plumb_supply_pipe_table_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_plumb_supply_pipe_by_gpm_table",
        subcategory="plumbing",
        display_name="Plumbing — Supply pipe size by GPM",
        data={
            "entries": [
                {"max_gpm": float(gpm), "pipe_size_mm": int(size)}
                for gpm, size in mep_kb.SUPPLY_PIPE_SIZE_MM_BY_GPM
            ],
            "velocity_target_fps": 5.0,
            "velocity_ceiling_fps": 8.0,
        },
        source_section="CPVC/PEX velocity-based supply sizing",
        source_tag="seed:mep.SUPPLY_PIPE_SIZE_MM_BY_GPM",
    )


def _plumb_hunters_curve_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_plumb_hunters_curve_flush_tank",
        subcategory="plumbing",
        display_name="Plumbing — Hunter's curve (flush-tank), WSFU → GPM",
        data={
            "entries": [
                {"wsfu": float(w), "gpm": float(g)}
                for w, g in mep_kb.HUNTERS_CURVE_FLUSH_TANK
            ]
        },
        notes="Predominantly flush-tank systems (IPC table E103.3).",
        source_section="IPC table E103.3",
        source_tag="seed:mep.HUNTERS_CURVE_FLUSH_TANK",
    )


def _plumb_vent_table_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_plumb_vent_stack_size_table",
        subcategory="plumbing",
        display_name="Plumbing — Vent stack size by DFU & length",
        data={
            "entries": [
                {
                    "max_dfu_on_stack": int(d),
                    "max_developed_length_m": int(L),
                    "vent_size_mm": int(v),
                }
                for d, L, v in mep_kb.VENT_STACK_SIZE_BY_DFU
            ]
        },
        source_section="IPC 906.1 / NBC Part 9 vent sizing",
        source_tag="seed:mep.VENT_STACK_SIZE_BY_DFU",
    )


def _plumb_trap_size_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_plumb_trap_{fixture}",
            subcategory="plumbing",
            display_name=f"Plumbing — Trap size, {fixture.replace('_', ' ')}",
            data={"fixture": fixture, **dict(spec)},
            source_section="IPC table 1002.1",
            source_tag="seed:mep.TRAP_SIZE_MM_PER_FIXTURE",
        )
        for fixture, spec in mep_kb.TRAP_SIZE_MM_PER_FIXTURE.items()
    ]


def _plumb_slope_rules_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_plumb_slope_rules",
        subcategory="plumbing",
        display_name="Plumbing — Drain & vent slope requirements",
        data=dict(mep_kb.SLOPE_REQUIREMENT),
        source_section="IPC drainage slope",
        source_tag="seed:mep.SLOPE_REQUIREMENT",
    )


def _plumb_water_demand_rows() -> list[dict[str, Any]]:
    return [
        _scalar_row(
            f"mep_plumb_water_demand_{use}",
            subcategory="plumbing",
            display_name=f"Plumbing — Water demand, {use.replace('_', ' ')}",
            data={"use_type": use, "litres_per_day_band": [int(lo), int(hi)]},
            source_section="NBC Part 9 / IS 1172 water demand",
            source_tag="seed:mep.WATER_DEMAND_LPM",
        )
        for use, (lo, hi) in mep_kb.WATER_DEMAND_LPM.items()
    ]


def _plumb_trap_notes_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_plumb_trap_notes",
        subcategory="plumbing",
        display_name="Plumbing — Trap rules + prohibitions",
        data=dict(mep_kb.TRAP_NOTES),
        source_section="IS 1742 / IPC 1002.3",
        source_tag="seed:mep.TRAP_NOTES",
    )


def _plumb_vent_rules_row() -> dict[str, Any]:
    return _scalar_row(
        "mep_plumb_vent_rules",
        subcategory="plumbing",
        display_name="Plumbing — Vent system rules",
        data=dict(mep_kb.VENT_RULES),
        source_section="IPC chapter 9 / NBC Part 9",
        source_tag="seed:mep.VENT_RULES",
    )


# ─────────────────────────────────────────────────────────────────────
# System cost rates (per m²)
# ─────────────────────────────────────────────────────────────────────


def _system_cost_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for system_key, spec in mep_kb.SYSTEM_COST_INR_PER_M2.items():
        lo, hi = spec["range"]
        rows.append(
            _scalar_row(
                f"mep_system_cost_{system_key}",
                subcategory="system_cost",
                display_name=f"MEP system cost — {system_key.replace('_', ' ')}",
                data={
                    "system_key": system_key,
                    "rate_inr_per_m2_low": float(lo),
                    "rate_inr_per_m2_high": float(hi),
                },
                notes=spec.get("notes"),
                source_section="BRD Layer 1B — MEP system cost rates",
                source_tag="seed:mep.SYSTEM_COST_INR_PER_M2",
            )
        )
    return rows


# ─────────────────────────────────────────────────────────────────────
# Public — single entry point
# ─────────────────────────────────────────────────────────────────────


def build_mep_seed_rows() -> list[dict[str, Any]]:
    """Every MEP standards row, ready for ``op.bulk_insert``."""
    return [
        # HVAC
        *_hvac_ach_rows(),
        *_hvac_cfm_per_person_rows(),
        *_hvac_cooling_load_rows(),
        *_hvac_duct_velocity_rows(),
        _hvac_equipment_band_row(),
        _hvac_duct_round_table_row(),
        *_hvac_register_rating_rows(),
        # Electrical
        *_elec_lux_rows(),
        *_elec_circuit_load_rows(),
        *_elec_power_density_rows(),
        *_elec_fixture_rows(),
        *_elec_outlet_rows(),
        *_elec_outlet_rule_rows(),
        *_elec_task_lighting_rows(),
        _elec_layout_rules_row(),
        # Plumbing
        *_plumb_dfu_rows(),
        *_plumb_wsfu_rows(),
        _plumb_pipe_by_dfu_table_row(),
        _plumb_supply_pipe_table_row(),
        _plumb_hunters_curve_row(),
        _plumb_vent_table_row(),
        *_plumb_trap_size_rows(),
        _plumb_slope_rules_row(),
        *_plumb_water_demand_rows(),
        _plumb_trap_notes_row(),
        _plumb_vent_rules_row(),
        # System cost rates
        *_system_cost_rows(),
    ]
