"""Service layer for the Design Brief Input System (Phase 1 / Layer 1A).

Responsible for cross-field validation, defaulting, and emitting a
knowledge-ready payload that downstream stages (theme engine, layout,
knowledge validator) can consume directly.
"""

from __future__ import annotations

import uuid

from app.knowledge import themes as theme_rules
from app.models.brief import (
    BriefThemeEnum,
    ClimaticZoneEnum,
    DesignBriefIn,
    DesignBriefOut,
    ProjectTypeEnum,
)


# Project-type → climatic-zone-agnostic defaults for code references.
_CODE_DEFAULTS: dict[ProjectTypeEnum, list[str]] = {
    ProjectTypeEnum.RESIDENTIAL: ["NBC-2016 Part 3"],
    ProjectTypeEnum.COMMERCIAL: ["NBC-2016 Part 4", "ECBC-2017"],
    ProjectTypeEnum.HOSPITALITY: ["NBC-2016 Part 4", "FSSAI-2011"],
    ProjectTypeEnum.INSTITUTIONAL: ["NBC-2016 Part 4", "IS-875"],
    ProjectTypeEnum.RETAIL: ["NBC-2016 Part 4"],
    ProjectTypeEnum.OFFICE: ["ECBC-2017"],
    ProjectTypeEnum.MIXED_USE: ["NBC-2016 Part 3", "NBC-2016 Part 4"],
    ProjectTypeEnum.INDUSTRIAL: ["NBC-2016 Part 4", "IS-875", "Factories Act 1948"],
    ProjectTypeEnum.CUSTOM: [],
}

# Coarse city→zone map. Conservative; the client can override.
_ZONE_BY_CITY: dict[str, ClimaticZoneEnum] = {
    "mumbai": ClimaticZoneEnum.WARM_HUMID,
    "chennai": ClimaticZoneEnum.WARM_HUMID,
    "kolkata": ClimaticZoneEnum.WARM_HUMID,
    "goa": ClimaticZoneEnum.WARM_HUMID,
    "bengaluru": ClimaticZoneEnum.TEMPERATE,
    "bangalore": ClimaticZoneEnum.TEMPERATE,
    "pune": ClimaticZoneEnum.TEMPERATE,
    "jaipur": ClimaticZoneEnum.HOT_DRY,
    "ahmedabad": ClimaticZoneEnum.HOT_DRY,
    "jodhpur": ClimaticZoneEnum.HOT_DRY,
    "delhi": ClimaticZoneEnum.COMPOSITE,
    "new_delhi": ClimaticZoneEnum.COMPOSITE,
    "lucknow": ClimaticZoneEnum.COMPOSITE,
    "shimla": ClimaticZoneEnum.COLD,
    "manali": ClimaticZoneEnum.COLD,
    "leh": ClimaticZoneEnum.COLD,
}


def _infer_climatic_zone(city: str) -> ClimaticZoneEnum | None:
    key = (city or "").strip().lower().replace(" ", "_")
    return _ZONE_BY_CITY.get(key)


def _ensure_theme_known(theme: BriefThemeEnum, custom_spec: str) -> list[str]:
    warnings: list[str] = []
    if theme == BriefThemeEnum.CUSTOM:
        return warnings
    if theme_rules.get(theme.value) is None:
        warnings.append(
            f"Theme '{theme.value}' has no parametric rule pack; generation will fall back to generic defaults."
        )
    return warnings


def validate_and_normalize(payload: DesignBriefIn) -> DesignBriefOut:
    """Run cross-field checks, fill defaults, and return a normalized brief."""
    warnings: list[str] = []

    # Theme sanity
    warnings.extend(_ensure_theme_known(payload.theme.theme, payload.theme.custom_spec))

    # Climatic-zone inference if missing
    regulatory = payload.regulatory.model_copy()
    if regulatory.climatic_zone is None and regulatory.city:
        inferred = _infer_climatic_zone(regulatory.city)
        if inferred is not None:
            regulatory.climatic_zone = inferred
            warnings.append(
                f"Climatic zone inferred as '{inferred.value}' from city '{regulatory.city}'; override explicitly if incorrect."
            )
        else:
            warnings.append(
                f"Climatic zone could not be inferred from city '{regulatory.city}'; proceeding without zone-specific rules."
            )

    # Building-code defaults
    if not regulatory.building_codes:
        defaults = _CODE_DEFAULTS.get(payload.project_type.type, [])
        if defaults:
            regulatory.building_codes = list(defaults)
            warnings.append(
                f"Building codes defaulted from project type '{payload.project_type.type.value}': {', '.join(defaults)}"
            )

    # Budget sanity vs area
    dims = payload.space.dimensions
    area = dims.length * dims.width
    if payload.requirements.budget is not None and area > 0:
        per_unit = payload.requirements.budget / area
        if per_unit < 100:
            warnings.append(
                f"Budget of {payload.requirements.budget} {payload.requirements.currency} over {area:.1f} {dims.unit}² is unusually low (~{per_unit:.1f}/{dims.unit}²)."
            )

    return DesignBriefOut(
        brief_id=uuid.uuid4().hex,
        status="accepted",
        project_type=payload.project_type,
        theme=payload.theme,
        space=payload.space,
        requirements=payload.requirements,
        regulatory=regulatory,
        warnings=warnings,
    )


def brief_to_generation_context(brief: DesignBriefOut) -> dict:
    """Flatten a validated brief into the dict shape used by the generation pipeline."""
    dims = brief.space.dimensions
    return {
        "project_type": brief.project_type.type.value,
        "project_sub_type": brief.project_type.sub_type,
        "project_scale": brief.project_type.scale,
        "theme": brief.theme.theme.value,
        "theme_custom_spec": brief.theme.custom_spec,
        "dimensions": dims.model_dump(),
        "site_conditions": brief.space.site_conditions.model_dump(),
        "constraints": list(brief.space.constraints),
        "functional_needs": list(brief.requirements.functional_needs),
        "aesthetic_preferences": list(brief.requirements.aesthetic_preferences),
        "narrative": brief.requirements.narrative,
        "budget": brief.requirements.budget,
        "currency": brief.requirements.currency,
        "timeline_weeks": brief.requirements.timeline_weeks,
        "regulatory": {
            "country": brief.regulatory.country,
            "state": brief.regulatory.state,
            "city": brief.regulatory.city,
            "postal_code": brief.regulatory.postal_code,
            "building_codes": list(brief.regulatory.building_codes),
            "climatic_zone": brief.regulatory.climatic_zone.value if brief.regulatory.climatic_zone else None,
            "compliance_notes": brief.regulatory.compliance_notes,
        },
    }
