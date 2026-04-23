"""Design Brief Input System (BRD Phase 1, Layer 1A).

Five-section structured intake that feeds the knowledge-validator, theme
engine, and generation pipeline. Kept intentionally permissive at the
field level and strict at the section level so the brief can be built up
interactively before being committed.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.design_intake import (
    parse_dimensions_input,
    validate_requirements_text,
)


# ── Enums ────────────────────────────────────────────────────────────────────


class ProjectTypeEnum(str, Enum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    HOSPITALITY = "hospitality"
    INSTITUTIONAL = "institutional"
    RETAIL = "retail"
    OFFICE = "office"
    MIXED_USE = "mixed_use"
    INDUSTRIAL = "industrial"
    CUSTOM = "custom"


class BriefThemeEnum(str, Enum):
    PEDESTAL = "pedestal"
    CONTEMPORARY = "contemporary"
    MODERN = "modern"
    MID_CENTURY_MODERN = "mid_century_modern"
    CUSTOM = "custom"


class ClimaticZoneEnum(str, Enum):
    HOT_DRY = "hot_dry"
    WARM_HUMID = "warm_humid"
    COMPOSITE = "composite"
    TEMPERATE = "temperate"
    COLD = "cold"


# ── Section 1: Project Type ──────────────────────────────────────────────────


class ProjectTypeSection(BaseModel):
    type: ProjectTypeEnum
    sub_type: str = Field(default="", max_length=120)
    scale: str = Field(default="", max_length=64)  # e.g. single-unit, tower, campus

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        value = data.get("type")
        if isinstance(value, str):
            data = dict(data)
            data["type"] = value.strip().lower().replace("-", "_").replace(" ", "_")
        return data


# ── Section 2: Theme Selection ───────────────────────────────────────────────


class ThemeSection(BaseModel):
    theme: BriefThemeEnum
    custom_spec: str = Field(default="", max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        value = data.get("theme")
        if isinstance(value, str):
            key = value.strip().lower().replace("-", "_").replace(" ", "_")
            aliases = {
                "midcentury": "mid_century_modern",
                "mid_century": "mid_century_modern",
                "mcm": "mid_century_modern",
                "plinth": "pedestal",
            }
            data = dict(data)
            data["theme"] = aliases.get(key, key)
        return data

    @model_validator(mode="after")
    def custom_requires_spec(self) -> "ThemeSection":
        if self.theme == BriefThemeEnum.CUSTOM and not self.custom_spec.strip():
            raise ValueError("custom_spec is required when theme='custom'")
        return self


# ── Section 3: Space Parameters ──────────────────────────────────────────────


class DimensionsIn(BaseModel):
    length: float = Field(gt=0)
    width: float = Field(gt=0)
    height: float | None = Field(default=None, gt=0)
    unit: str

    @field_validator("unit", mode="before")
    @classmethod
    def normalize_unit(cls, value: str) -> str:
        normalized = str(value).strip().lower()
        if normalized in {"ft", "feet"}:
            return "ft"
        if normalized in {"m", "meter", "meters"}:
            return "m"
        raise ValueError("Dimensions unit must be 'ft' or 'm'")


class SiteConditions(BaseModel):
    orientation: str = Field(default="", max_length=32)  # N/S/E/W/NE...
    floor_level: str = Field(default="", max_length=32)  # ground, 3rd, penthouse
    access: str = Field(default="", max_length=120)
    existing_features: list[str] = Field(default_factory=list)
    natural_light: str = Field(default="", max_length=64)
    ventilation: str = Field(default="", max_length=64)
    noise_context: str = Field(default="", max_length=120)


class SpaceParameters(BaseModel):
    dimensions: DimensionsIn
    constraints: list[str] = Field(default_factory=list)
    site_conditions: SiteConditions = Field(default_factory=SiteConditions)

    @field_validator("dimensions", mode="before")
    @classmethod
    def coerce_dims(cls, value: Any) -> Any:
        if isinstance(value, (str, dict)):
            return parse_dimensions_input(value)
        return value


# ── Section 4: Client Requirements ───────────────────────────────────────────


class ClientRequirements(BaseModel):
    functional_needs: list[str] = Field(default_factory=list)
    aesthetic_preferences: list[str] = Field(default_factory=list)
    narrative: str = Field(default="", max_length=5000)
    budget: float | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", max_length=8)
    timeline_weeks: int | None = Field(default=None, ge=0)

    @field_validator("currency", mode="before")
    @classmethod
    def upper_currency(cls, value: str) -> str:
        return str(value).strip().upper() or "INR"

    @model_validator(mode="after")
    def has_enough_signal(self) -> "ClientRequirements":
        if not (self.functional_needs or self.aesthetic_preferences or self.narrative.strip()):
            raise ValueError(
                "Provide at least one functional_need, aesthetic_preference, or narrative"
            )
        if self.narrative.strip():
            validate_requirements_text(self.narrative)
        return self


# ── Section 5: Regulatory Context ────────────────────────────────────────────


class RegulatoryContext(BaseModel):
    country: str = Field(default="", max_length=80)
    state: str = Field(default="", max_length=80)
    city: str = Field(default="", max_length=120)
    postal_code: str = Field(default="", max_length=20)
    building_codes: list[str] = Field(default_factory=list)  # e.g. ["NBC-2016", "IS-875"]
    climatic_zone: ClimaticZoneEnum | None = None
    compliance_notes: str = Field(default="", max_length=2000)

    @model_validator(mode="before")
    @classmethod
    def normalize(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        zone = data.get("climatic_zone")
        if isinstance(zone, str):
            data["climatic_zone"] = zone.strip().lower().replace("-", "_").replace(" ", "_")
        return data


# ── Composite Brief ──────────────────────────────────────────────────────────


class DesignBriefIn(BaseModel):
    """Complete five-section design brief accepted at the API boundary."""

    project_type: ProjectTypeSection
    theme: ThemeSection
    space: SpaceParameters
    requirements: ClientRequirements
    regulatory: RegulatoryContext = Field(default_factory=RegulatoryContext)
    notes: str = Field(default="", max_length=5000)


class DesignBriefOut(BaseModel):
    brief_id: str
    status: str
    project_type: ProjectTypeSection
    theme: ThemeSection
    space: SpaceParameters
    requirements: ClientRequirements
    regulatory: RegulatoryContext
    warnings: list[str] = Field(default_factory=list)
