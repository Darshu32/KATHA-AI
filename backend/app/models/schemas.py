"""Pydantic schemas for API request/response validation."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


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
