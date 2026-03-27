"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.services.design_intake import (
    parse_dimensions_input,
    validate_requirements_text,
)


# ── Enums ────────────────────────────────────────────────────────────────────


class ProjectStatus(str, Enum):
    DRAFT = "draft"
    GENERATING = "generating"
    READY = "ready"
    ARCHIVED = "archived"


class GenerationStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class ChangeType(str, Enum):
    INITIAL = "initial"
    PROMPT_EDIT = "prompt_edit"
    MANUAL_EDIT = "manual_edit"
    THEME_SWITCH = "theme_switch"
    MATERIAL_CHANGE = "material_change"


class ThemeEnum(str, Enum):
    MODERN = "modern"
    CONTEMPORARY = "contemporary"
    MINIMALIST = "minimalist"
    TRADITIONAL = "traditional"
    RUSTIC = "rustic"
    INDUSTRIAL = "industrial"
    SCANDINAVIAN = "scandinavian"
    BOHEMIAN = "bohemian"
    LUXURY = "luxury"
    COASTAL = "coastal"


class DesignStatus(str, Enum):
    ACCEPTED = "accepted"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


# ── Project Schemas ──────────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=2000)
    prompt: str = Field(min_length=10, max_length=5000)
    room_type: str = Field(default="living_room", max_length=64)
    style: str = Field(default="modern", max_length=64)


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: ProjectStatus | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    latest_version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListOut(BaseModel):
    projects: list[ProjectOut]
    total: int


# ── Design Graph Schemas ─────────────────────────────────────────────────────


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Dimensions(BaseModel):
    length: float
    width: float
    height: float


class DesignObjectSchema(BaseModel):
    id: str
    type: str  # wall | door | window | sofa | table | chair | light | ...
    name: str = ""
    position: Vec3 = Field(default_factory=Vec3)
    rotation: Vec3 = Field(default_factory=Vec3)
    dimensions: Dimensions | None = None
    material: str = ""
    color: str = ""
    style: str = ""
    parent_id: str | None = None
    metadata: dict = Field(default_factory=dict)


class MaterialSchema(BaseModel):
    id: str
    name: str
    category: str = ""  # wood | stone | fabric | metal | glass | paint | tile
    color: str = ""
    texture_url: str = ""
    unit_rate: float = 0.0
    unit: str = "sqft"


class LightingSchema(BaseModel):
    id: str
    type: str  # ambient | point | spot | directional | area
    position: Vec3 = Field(default_factory=Vec3)
    intensity: float = 1.0
    color: str = "#FFFFFF"
    target_id: str | None = None


class SpaceSchema(BaseModel):
    id: str
    name: str
    room_type: str
    dimensions: Dimensions
    objects: list[str] = Field(default_factory=list)  # object IDs in this space


class DesignGraphOut(BaseModel):
    project_id: str
    version: int
    design_type: str
    style: dict
    site: dict
    spaces: list[SpaceSchema]
    objects: list[DesignObjectSchema]
    materials: list[MaterialSchema]
    lighting: list[LightingSchema]
    constraints: list[dict] = Field(default_factory=list)
    estimation: dict = Field(default_factory=dict)
    assets: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


# ── Prompt / Generation Schemas ──────────────────────────────────────────────


class PromptRequest(BaseModel):
    prompt: str = Field(min_length=10, max_length=5000)
    room_type: str = Field(default="living_room")
    style: str = Field(default="modern")
    dimensions: Dimensions | None = None


class LocalEditRequest(BaseModel):
    object_id: str
    prompt: str = Field(min_length=5, max_length=2000)


class ThemeSwitchRequest(BaseModel):
    new_style: str = Field(min_length=2, max_length=64)
    preserve_layout: bool = True


class GenerationResponse(BaseModel):
    project_id: str
    version: int
    status: GenerationStatus
    task_id: str | None = None


class DesignDimensions(BaseModel):
    length: float = Field(gt=0)
    width: float = Field(gt=0)
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


class DesignRequest(BaseModel):
    roomType: str
    theme: ThemeEnum
    dimensions: DesignDimensions | str
    requirements: str
    budget: float | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_payload(cls, data: object):
        if not isinstance(data, dict):
            return data

        normalized: dict[str, Any] = dict(data)
        for field_name in ("roomType", "theme", "requirements"):
            value = normalized.get(field_name)
            if isinstance(value, str):
                normalized[field_name] = value.strip()

        if isinstance(normalized.get("roomType"), str):
            normalized["roomType"] = normalized["roomType"].lower().replace("-", "_").replace(" ", "_")

        if isinstance(normalized.get("theme"), str):
            normalized["theme"] = normalized["theme"].lower()

        dimensions = normalized.get("dimensions")
        if isinstance(dimensions, (str, dict)):
            normalized["dimensions"] = parse_dimensions_input(dimensions)

        return normalized

    @field_validator("dimensions", mode="before")
    @classmethod
    def validate_dimensions(cls, value: DesignDimensions | str | dict[str, Any]) -> DesignDimensions:
        return parse_dimensions_input(value)

    @field_validator("roomType")
    @classmethod
    def validate_room_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Room type must be provided")
        return value

    @field_validator("requirements")
    @classmethod
    def validate_requirements(cls, value: str) -> str:
        validate_requirements_text(value)
        return value

    @field_validator("budget")
    @classmethod
    def validate_budget(cls, value: float | None) -> float | None:
        if value is not None and value < 0:
            raise ValueError("Budget must be greater than or equal to 0")
        return value


class DesignResponse(BaseModel):
    designId: str
    status: DesignStatus
    message: str
    createdAt: datetime


class DesignOut(BaseModel):
    id: str
    room_type: str
    theme: ThemeEnum
    dimensions: DesignDimensions
    requirements: str
    budget: float | None
    status: DesignStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class ErrorDetail(BaseModel):
    field: str | None = None
    message: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


# ── Estimate Schemas ─────────────────────────────────────────────────────────


class EstimateLineItemOut(BaseModel):
    category: str
    item_name: str
    material: str
    quantity: float
    unit: str
    unit_rate_low: float
    unit_rate_high: float
    total_low: float
    total_high: float

    model_config = {"from_attributes": True}


class EstimateOut(BaseModel):
    id: str
    status: str
    total_low: float
    total_high: float
    currency: str
    assumptions: dict
    line_items: list[EstimateLineItemOut]

    model_config = {"from_attributes": True}


# ── Auth Schemas ─────────────────────────────────────────────────────────────


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=120)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    is_active: bool

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
