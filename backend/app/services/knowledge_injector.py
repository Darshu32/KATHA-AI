"""Input-stage knowledge injector (BRD Phase 1 / Layer 1A).

Given a validated DesignBrief, assemble the knowledge bundle that is
meaningful *at input time*:

  1. Standard dimensions (doors, windows, corridors, stairs, ceiling, clearances)
  2. Building code requirements (fire egress, structural, ventilation, accessibility)
  3. Climate-specific considerations (orientation, glazing, HVAC, passive strategy)
  4. Material availability by region (local vs transported, price index)

The output is intentionally structured (not a prose blob) so downstream
stages — theme engine, layout, estimator, LLM prompt builder — can pick
the slices they need without re-computing.
"""

from __future__ import annotations

from typing import Any

from app.knowledge import (
    clearances,
    climate,
    codes,
    ibc,
    manufacturing,
    mep,
    regional_materials,
    space_standards,
    structural,
    themes,
)
from app.models.brief import (
    BriefThemeEnum,
    DesignBriefOut,
    ProjectTypeEnum,
)


# Project type → space_standards segment used by the knowledge tables.
_SEGMENT_BY_PROJECT_TYPE: dict[ProjectTypeEnum, str] = {
    ProjectTypeEnum.RESIDENTIAL: "residential",
    ProjectTypeEnum.COMMERCIAL: "commercial",
    ProjectTypeEnum.OFFICE: "commercial",
    ProjectTypeEnum.RETAIL: "commercial",
    ProjectTypeEnum.HOSPITALITY: "hospitality",
    ProjectTypeEnum.INSTITUTIONAL: "commercial",
    ProjectTypeEnum.MIXED_USE: "commercial",
    ProjectTypeEnum.INDUSTRIAL: "commercial",
    ProjectTypeEnum.CUSTOM: "residential",
}


def _segment(project_type: ProjectTypeEnum) -> str:
    return _SEGMENT_BY_PROJECT_TYPE.get(project_type, "residential")


# ── 1. Standard dimensions ──────────────────────────────────────────────────

def _standard_dimensions(segment: str) -> dict[str, Any]:
    corridor_spec = clearances.CORRIDORS.get(
        "residential" if segment == "residential" else "commercial",
        clearances.CORRIDORS["residential"],
    )
    stair_spec = clearances.STAIRS.get(
        "residential" if segment == "residential" else "commercial",
        clearances.STAIRS["residential"],
    )
    habitable = codes.NBC_INDIA["minimum_room_dimensions"]
    return {
        "doors": {
            "main_entry_width_mm": clearances.DOORS["main_entry"]["width_mm"],
            "interior_width_mm": clearances.DOORS["interior"]["width_mm"],
            "bathroom_width_mm": clearances.DOORS["bathroom"]["width_mm"],
            "emergency_egress_width_mm": clearances.DOORS["emergency_egress"]["width_mm"],
        },
        "windows": {
            "bedroom": clearances.WINDOWS["bedroom_standard"],
            "living": clearances.WINDOWS["living_picture"],
            "bathroom": clearances.WINDOWS["bathroom_vent"],
            "kitchen": clearances.WINDOWS["kitchen"],
        },
        "corridor_min_width_mm": corridor_spec["min_width_mm"],
        "corridor_preferred_mm": corridor_spec.get("preferred_mm"),
        "stair": {
            "rise_mm": stair_spec["rise_mm"],
            "tread_mm": stair_spec["tread_mm"],
            "min_width_mm": stair_spec["min_width_mm"],
            "headroom_mm": stair_spec.get("headroom_mm"),
        },
        "ceiling_height_min_m": habitable["habitable_room_min_height_m"],
        "circulation_mm": dict(clearances.CIRCULATION),
        "manufacturing_tolerances_mm": {
            name: spec["+-mm"] for name, spec in manufacturing.TOLERANCES.items()
        } if hasattr(manufacturing, "TOLERANCES") else {},
    }


# ── 2. Building code requirements ───────────────────────────────────────────

def _building_codes(
    project_type: ProjectTypeEnum,
    requested_codes: list[str],
    segment: str,
) -> dict[str, Any]:
    nbc_min = codes.NBC_INDIA["minimum_room_dimensions"]
    egress_key = "max_travel_residential_m" if segment == "residential" else "max_travel_commercial_m"
    return {
        "applicable_codes": list(requested_codes),
        "habitable_min_area_m2": nbc_min["habitable_room_min_area_m2"],
        "habitable_min_short_side_m": nbc_min["habitable_room_min_short_side_m"],
        "habitable_min_height_m": nbc_min["habitable_room_min_height_m"],
        "kitchen_min_area_m2": nbc_min["kitchen_min_area_m2"],
        "bathroom_min_area_m2": nbc_min["bathroom_min_area_m2"],
        "ventilation_openable_percent_floor": codes.NBC_INDIA["ventilation"]["openable_area_percent_floor"],
        "natural_light_glazing_percent_floor": codes.NBC_INDIA["natural_light"]["glazing_percent_floor"],
        "fire_egress": {
            "max_travel_distance_m": codes.NBC_INDIA["fire_egress"][egress_key],
            "min_exit_count_over_500m2_floor": codes.NBC_INDIA["fire_egress"]["min_exit_count_over_500m2_floor"],
            "fire_door_rating_min_hr": codes.NBC_INDIA["fire_egress"]["fire_door_rating_min_hr"],
            "corridor_min_width_mm": codes.NBC_INDIA["fire_egress"]["corridor_min_width_mm"],
        },
        "structural_references": ["IS-875 (loads)", "IS-456 (RCC)", "IS-800 (steel)"],
        "accessibility": dict(codes.ACCESSIBILITY),
        "energy_envelope_ecbc": {
            "wall_u_value_w_m2k": codes.ECBC["envelope_U_value_wall_w_m2k"],
            "roof_u_value_w_m2k": codes.ECBC["envelope_U_value_roof_w_m2k"],
            "wwr_max": codes.ECBC["window_wall_ratio_max"],
            "applies_when": codes.ECBC["notes"],
        },
    }


# ── 3. Climate-specific considerations ──────────────────────────────────────

def _climate_considerations(zone_value: str | None) -> dict[str, Any]:
    pack = climate.get(zone_value) or {}
    if not pack:
        return {"zone": zone_value, "available": False}
    return {
        "zone": zone_value,
        "available": True,
        "display_name": pack["display_name"],
        "design_temp_c": pack["design_temp_c"],
        "humidity_percent": pack["humidity_percent"],
        "preferred_orientation": pack["preferred_orientation"],
        "glazing": pack["glazing"],
        "wall_strategy": pack["wall_strategy"],
        "roof_strategy": pack["roof_strategy"],
        "hvac": pack["hvac"],
        "passive_priorities": list(pack["passive_priorities"]),
    }


# ── 4. Material availability by region ──────────────────────────────────────

def _material_availability(theme_value: str, city: str | None) -> dict[str, Any]:
    pack = themes.get(theme_value) or {}
    palette = pack.get("material_palette", {})
    themed_materials: list[str] = []
    for bucket in ("primary", "secondary", "upholstery", "accent"):
        themed_materials.extend(palette.get(bucket, []))

    report = regional_materials.availability_report(themed_materials, city)
    report["themed_materials"] = themed_materials
    report["city"] = city
    return report


# ── 5. Structural logic ─────────────────────────────────────────────────────

def _structural_logic(project_type: ProjectTypeEnum, segment: str) -> dict[str, Any]:
    # Pick the most relevant live-load row for the project type.
    live_load_key = {
        ProjectTypeEnum.RESIDENTIAL: "residential_room",
        ProjectTypeEnum.COMMERCIAL: "office_general",
        ProjectTypeEnum.OFFICE: "office_general",
        ProjectTypeEnum.RETAIL: "retail_floor",
        ProjectTypeEnum.HOSPITALITY: "hotel_room",
        ProjectTypeEnum.INSTITUTIONAL: "office_general",
        ProjectTypeEnum.MIXED_USE: "office_general",
        ProjectTypeEnum.INDUSTRIAL: "warehouse_light",
        ProjectTypeEnum.CUSTOM: "residential_room",
    }.get(project_type, "residential_room")

    column_bay_key = {
        ProjectTypeEnum.RESIDENTIAL: "residential",
        ProjectTypeEnum.COMMERCIAL: "commercial_office",
        ProjectTypeEnum.OFFICE: "commercial_office",
        ProjectTypeEnum.RETAIL: "commercial_office",
        ProjectTypeEnum.HOSPITALITY: "commercial_office",
        ProjectTypeEnum.INSTITUTIONAL: "commercial_office",
        ProjectTypeEnum.MIXED_USE: "commercial_office",
        ProjectTypeEnum.INDUSTRIAL: "industrial",
    }.get(project_type, "residential")

    return {
        "live_load_kn_m2": structural.LIVE_LOADS_KN_PER_M2.get(live_load_key),
        "live_load_reference": live_load_key,
        "dead_load_reference_kn_m2": {
            "rcc_slab_150mm": structural.DEAD_LOADS_KN_PER_M2["rcc_slab_150mm"],
            "brick_wall_230mm_per_m_height": structural.DEAD_LOADS_KN_PER_M2["brick_wall_230mm"],
            "finishes_waterproofing": structural.DEAD_LOADS_KN_PER_M2["waterproofing_finishes"],
        },
        "column_spacing_m": structural.COLUMN_SPACING_M.get(column_bay_key),
        "span_limits_m": {
            "rcc_beam": structural.SPAN_LIMITS_M["rcc_beam"],
            "steel_i_beam": structural.SPAN_LIMITS_M["steel_i_beam"],
            "timber_beam": structural.SPAN_LIMITS_M["timber_beam"],
            "rcc_flat_slab": structural.SPAN_LIMITS_M["rcc_flat_slab"],
        },
        "foundation_by_soil": {k: dict(v) for k, v in structural.FOUNDATION_BY_SOIL.items()},
        "wind_loads_kn_m2": dict(structural.WIND_LOADS_KN_PER_M2),
        "seismic_zones": {k: dict(v) for k, v in structural.SEISMIC_ZONES.items()},
        "typical_concrete_grade": "M25 (residential), M30 (seismic / commercial)",
    }


# ── 6. MEP strategy ─────────────────────────────────────────────────────────

def _mep_strategy(project_type: ProjectTypeEnum, area_m2: float) -> dict[str, Any]:
    # Choose the right cooling / CFM / lux rows based on project type.
    cooling_key = {
        ProjectTypeEnum.RESIDENTIAL: "residential",
        ProjectTypeEnum.COMMERCIAL: "office_general",
        ProjectTypeEnum.OFFICE: "office_general",
        ProjectTypeEnum.RETAIL: "retail",
        ProjectTypeEnum.HOSPITALITY: "residential",
        ProjectTypeEnum.INSTITUTIONAL: "office_general",
        ProjectTypeEnum.MIXED_USE: "office_general",
        ProjectTypeEnum.INDUSTRIAL: "office_general",
    }.get(project_type, "residential")

    cfm_key = {
        ProjectTypeEnum.RESIDENTIAL: "residential",
        ProjectTypeEnum.OFFICE: "office",
        ProjectTypeEnum.COMMERCIAL: "office",
        ProjectTypeEnum.RETAIL: "retail",
        ProjectTypeEnum.HOSPITALITY: "residential",
        ProjectTypeEnum.INSTITUTIONAL: "office",
        ProjectTypeEnum.MIXED_USE: "office",
        ProjectTypeEnum.INDUSTRIAL: "office",
    }.get(project_type, "residential")

    # Rough TR estimate for the envelope area.
    tr_factor = mep.COOLING_LOAD_TR_PER_M2.get(cooling_key, mep.COOLING_LOAD_TR_PER_M2["residential"])
    estimated_tr = round(area_m2 * tr_factor, 2) if area_m2 > 0 else None

    # System cost buckets appropriate to project type.
    if project_type == ProjectTypeEnum.RESIDENTIAL:
        system_keys = ["hvac_split_residential", "electrical_residential", "plumbing_residential"]
    elif project_type == ProjectTypeEnum.INDUSTRIAL:
        system_keys = ["electrical_commercial", "plumbing_commercial", "fire_fighting_commercial"]
    else:
        system_keys = [
            "hvac_vrf_commercial",
            "electrical_commercial",
            "plumbing_commercial",
            "fire_fighting_commercial",
            "low_voltage_commercial",
        ]

    cost_envelope = {
        key: mep.system_cost_estimate(key, area_m2)
        for key in system_keys
        if area_m2 > 0
    }

    return {
        "hvac": {
            "cfm_per_person": mep.CFM_PER_PERSON.get(cfm_key),
            "cfm_reference": cfm_key,
            "cooling_load_tr_per_m2": tr_factor,
            "estimated_plant_tr": estimated_tr,
            "air_changes_per_hour": {
                "bedroom": mep.AIR_CHANGES_PER_HOUR["bedroom"],
                "living_room": mep.AIR_CHANGES_PER_HOUR["living_room"],
                "kitchen_exhaust": mep.AIR_CHANGES_PER_HOUR["kitchen"],
                "bathroom_exhaust": mep.AIR_CHANGES_PER_HOUR["bathroom"],
                "office_general": mep.AIR_CHANGES_PER_HOUR["office_general"],
                "conference": mep.AIR_CHANGES_PER_HOUR["conference_room"],
            },
            "duct_velocity_m_s": dict(mep.DUCT_VELOCITY_M_S),
        },
        "electrical": {
            "power_density_w_m2": mep.POWER_DENSITY_W_PER_M2.get(cooling_key),
            "lux_levels": {
                k: mep.LUX_LEVELS[k]
                for k in mep.LUX_LEVELS
                if k.startswith(
                    {
                        ProjectTypeEnum.RESIDENTIAL: ("bedroom", "living", "kitchen", "bathroom", "corridor", "staircase"),
                        ProjectTypeEnum.OFFICE: ("office", "conference", "corridor"),
                        ProjectTypeEnum.COMMERCIAL: ("office", "conference", "corridor"),
                        ProjectTypeEnum.RETAIL: ("retail", "corridor"),
                        ProjectTypeEnum.HOSPITALITY: ("bedroom", "restaurant", "corridor"),
                    }.get(project_type, ("office",))
                )
            },
            "circuit_load_w": dict(mep.CIRCUIT_LOAD_W),
        },
        "plumbing": {
            "dfu_per_fixture": dict(mep.DFU_PER_FIXTURE),
            "slope_per_metre": dict(mep.SLOPE_PER_METRE),
            "water_demand_lpm": dict(mep.WATER_DEMAND_LPM),
        },
        "system_cost_envelope_inr": cost_envelope,
    }


# ── 7. International code overlay ───────────────────────────────────────────

def _international_overlay(country: str | None) -> dict[str, Any] | None:
    """Include IBC summary when the project is outside India."""
    if not country:
        return None
    key = country.strip().lower()
    if key in {"india", "bharat", "in", ""}:
        return None
    return {
        "applicable": "IBC 2021 / IECC",
        "occupancy_groups": dict(ibc.OCCUPANCY_GROUPS),
        "egress": dict(ibc.EGRESS),
        "accessibility": dict(ibc.ACCESSIBILITY),
        "interior_environment": dict(ibc.INTERIOR_ENVIRONMENT),
        "energy_envelope_u_values_w_m2k": dict(ibc.ENERGY_ENVELOPE_U_VALUES_W_M2K),
    }


# ── Room-program suggestion based on project type ───────────────────────────

def _suggested_room_program(segment: str) -> dict[str, dict]:
    table = {
        "residential": space_standards.RESIDENTIAL,
        "commercial": space_standards.COMMERCIAL,
        "hospitality": space_standards.HOSPITALITY,
    }.get(segment, {})
    # Keep it compact — only the fields generation will consume.
    return {
        room: {
            "min_area_m2": spec.get("min_area_m2"),
            "typical_area_m2": spec.get("typical_area_m2"),
            "min_short_side_m": spec.get("min_short_side_m"),
            "min_height_m": spec.get("min_height_m"),
            "notes": spec.get("notes"),
        }
        for room, spec in table.items()
    }


# ── Public API ──────────────────────────────────────────────────────────────

def inject_knowledge(brief: DesignBriefOut) -> dict[str, Any]:
    """Return the full input-stage knowledge bundle for a validated brief."""
    segment = _segment(brief.project_type.type)
    zone_value = brief.regulatory.climatic_zone.value if brief.regulatory.climatic_zone else None
    dims = brief.space.dimensions
    area_m2 = dims.length * dims.width
    if dims.unit == "ft":
        area_m2 *= 0.092903

    bundle = {
        "brief_id": brief.brief_id,
        "segment": segment,
        "theme": brief.theme.theme.value,
        "footprint_area_m2": round(area_m2, 2),
        "standard_dimensions": _standard_dimensions(segment),
        "building_codes": _building_codes(
            brief.project_type.type,
            brief.regulatory.building_codes,
            segment,
        ),
        "climate": _climate_considerations(zone_value),
        "regional_materials": _material_availability(brief.theme.theme.value, brief.regulatory.city),
        "structural": _structural_logic(brief.project_type.type, segment),
        "mep": _mep_strategy(brief.project_type.type, area_m2),
        "room_program_reference": _suggested_room_program(segment),
    }
    overlay = _international_overlay(brief.regulatory.country)
    if overlay is not None:
        bundle["international_code_overlay"] = overlay

    if brief.theme.theme != BriefThemeEnum.CUSTOM:
        theme_pack = themes.get(brief.theme.theme.value)
        if theme_pack:
            bundle["theme_rules"] = {
                "display_name": theme_pack.get("display_name"),
                "material_palette": theme_pack.get("material_palette", {}),
                "colour_palette": theme_pack.get("colour_palette", []),
                "signature_moves": theme_pack.get("signature_moves", []),
                "dos": theme_pack.get("dos", []),
                "donts": theme_pack.get("donts", []),
                "ergonomic_targets": theme_pack.get("ergonomic_targets", {}),
            }
    return bundle


def build_prompt_preamble(brief: DesignBriefOut, bundle: dict[str, Any] | None = None) -> str:
    """Compact text block for LLM grounding. Pulls from the bundle when given."""
    bundle = bundle or inject_knowledge(brief)
    segment = bundle["segment"]
    std = bundle["standard_dimensions"]
    cd = bundle["building_codes"]
    cl = bundle["climate"]
    rm = bundle["regional_materials"]

    lines: list[str] = []
    lines.append(f"[Input-stage knowledge — {segment}]")
    lines.append(
        f"Doors mm: main {std['doors']['main_entry_width_mm']}, interior {std['doors']['interior_width_mm']}, "
        f"bathroom {std['doors']['bathroom_width_mm']}. Corridor >= {std['corridor_min_width_mm']}mm. "
        f"Ceiling >= {std['ceiling_height_min_m']}m."
    )
    lines.append(
        f"Codes: habitable >= {cd['habitable_min_area_m2']}m² / "
        f"{cd['habitable_min_short_side_m']}m short side. "
        f"Vent openable {cd['ventilation_openable_percent_floor']}% floor. "
        f"Daylight glazing >= {cd['natural_light_glazing_percent_floor']}% floor. "
        f"Fire travel <= {cd['fire_egress']['max_travel_distance_m']}m."
    )
    if cd.get("applicable_codes"):
        lines.append("Applicable: " + ", ".join(cd["applicable_codes"]))
    if cl.get("available"):
        orient = cl["preferred_orientation"]
        lines.append(
            f"Climate [{cl['display_name']}]: long axis {orient.get('long_axis','?')}, "
            f"openings {orient.get('primary_openings','?')}; "
            f"WWR <= {cl['glazing']['window_wall_ratio_max']}; "
            f"passive — {'; '.join(cl['passive_priorities'])}"
        )
    if rm.get("themed_materials"):
        local = ", ".join(rm["locally_available"]) or "none"
        remote = ", ".join(rm["requires_transport"]) or "none"
        lines.append(
            f"Materials at {rm.get('city') or 'site'}: local=[{local}] "
            f"transported=[{remote}] price-index={rm['city_price_index']}"
        )

    st = bundle.get("structural", {})
    if st:
        lines.append(
            f"Structural: LL {st.get('live_load_kn_m2')}kN/m² ({st.get('live_load_reference')}), "
            f"column bay {st.get('column_spacing_m')}m, "
            f"RCC beam span {st.get('span_limits_m', {}).get('rcc_beam')}m, "
            f"steel span {st.get('span_limits_m', {}).get('steel_i_beam')}m."
        )

    mp = bundle.get("mep", {})
    if mp:
        hv = mp.get("hvac", {})
        el = mp.get("electrical", {})
        lines.append(
            f"MEP: cooling {hv.get('cooling_load_tr_per_m2')}TR/m² (~{hv.get('estimated_plant_tr')}TR plant), "
            f"fresh air {hv.get('cfm_per_person')}CFM/person, "
            f"power density {el.get('power_density_w_m2')}W/m²."
        )
        if mp.get("system_cost_envelope_inr"):
            system_bits = []
            for key, spec in mp["system_cost_envelope_inr"].items():
                lo = spec["total_inr"]["low"]
                hi = spec["total_inr"]["high"]
                system_bits.append(f"{key}: ₹{lo/1e5:.1f}–{hi/1e5:.1f}L")
            lines.append("MEP cost envelope: " + "; ".join(system_bits))

    if bundle.get("international_code_overlay"):
        lines.append("International overlay: IBC 2021 summary attached (non-India project).")
    return "\n".join(lines)
