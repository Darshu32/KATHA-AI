"""Typed spatial spec — the formal contract the loose DesignGraph resolves into.

The graph the LLM emits is intentionally loose (``spaces`` / ``objects`` /
``constraints`` are ``list[dict]``). This module defines the canonical *typed*
structures that downstream consumers — the geometry kernel, the drawing
renderers, the exporters, and a future planegcs constraint solver — can rely on:

    RoomEnvelope · Wall · Opening · SpatialObject · Adjacency · Constraint
        └────────────────────── SpatialModel ──────────────────────┘

The resolver that upgrades a graph into a ``SpatialModel`` lives in
``app.services.spatial_resolver`` (it reuses the shared ``wall_model`` so the
walls/openings match the IFC export and section/elevation drawings exactly).

Coordinate model (post-normalization, metres): room length ``L`` spans x, width
``W`` spans z (floor plane), height ``H`` = y.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, computed_field

Side = Literal["south", "north", "west", "east"]


class Vec3(BaseModel):
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


class Dimensions(BaseModel):
    length: float = 0.0  # x extent
    width: float = 0.0   # z extent
    height: float = 0.0  # y extent


class RoomEnvelope(BaseModel):
    length: float
    width: float
    height: float


class Opening(BaseModel):
    """A window or door punched into a wall (voids it; not a floating box)."""

    source_id: str
    kind: Literal["window", "door"]
    center: float  # midpoint measured along the wall from its start
    width: float   # extent along the wall
    sill: float    # bottom height above floor
    head: float    # top height above floor

    @computed_field  # type: ignore[prop-decorator]
    @property
    def height(self) -> float:
        return max(self.head - self.sill, 0.0)


class Wall(BaseModel):
    id: str
    side: Side
    runs: Literal["x", "z"]  # axis the wall length runs along
    at: float                # fixed coord (z for south/north, x for west/east)
    length: float
    height: float
    thickness: float
    openings: list[Opening] = Field(default_factory=list)


class SpatialObject(BaseModel):
    """A furniture / equipment / massing element — a positioned solid."""

    id: str
    type: str = "object"
    role: str = "furniture"
    position: Vec3 = Field(default_factory=Vec3)
    dimensions: Dimensions = Field(default_factory=Dimensions)
    rotation_y: float = 0.0  # degrees about the vertical axis
    material: str | None = None


class Adjacency(BaseModel):
    """A connection between two spaces (or a space and the outside), through an
    opening — the seed of a circulation graph."""

    a: str
    b: str
    via: str | None = None  # connecting opening's source_id


class Constraint(BaseModel):
    """An explicit geometric relationship — the input a constraint solver
    (planegcs) needs. Not yet solved; formalised here so generation / editing can
    start emitting them."""

    kind: Literal["coincident", "align_x", "align_z", "distance", "angle", "fixed"]
    refs: list[str] = Field(default_factory=list)  # object / wall ids
    value: float | None = None


class SpatialModel(BaseModel):
    """The resolved, typed spatial model — one source of truth for geometry,
    drawings, export, and constraints."""

    kind: Literal["interior", "exterior"] = "interior"
    room: RoomEnvelope | None = None       # None for site-scale / exterior
    thickness: float = 0.15
    walls: list[Wall] = Field(default_factory=list)
    objects: list[SpatialObject] = Field(default_factory=list)
    adjacencies: list[Adjacency] = Field(default_factory=list)
    constraints: list[Constraint] = Field(default_factory=list)
