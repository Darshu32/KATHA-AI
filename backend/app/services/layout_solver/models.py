"""Public data model for the deterministic layout solver.

The solver turns a *program* — rooms with target areas plus the adjacencies that
must hold between them — into a *solution*: a set of non-overlapping room
rectangles that tile a boundary. It is the geometric layer under the LLM's
program graph (§4 of ``docs/how-this-works.md``): the language model decides
*what rooms and which adjacencies*; this decides *where*, deterministically.

Coordinate model (metres, matches ``app.models.spatial_spec``): a room occupies
``[x, x+length]`` on the x axis (length) and ``[z, z+width]`` on the z axis
(depth). ``y`` is up and is not a layout concern.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RoomSpec(BaseModel):
    """One room in the program: a target area and how square it wants to be."""

    id: str
    name: str = ""
    area: float = Field(gt=0)  # target floor area, m²
    # Aspect = longer_side / shorter_side. Rooms above this are penalised as
    # slivers during the search (area stays exact; proportion is what we tune).
    max_aspect: float = 2.2


class LayoutProgram(BaseModel):
    """The full solve request."""

    rooms: list[RoomSpec]
    # Undirected pairs of room ids that must share a wall segment.
    adjacencies: list[tuple[str, str]] = Field(default_factory=list)
    # Explicit site footprint (length x, depth z) in metres. When omitted it is
    # derived from the total program area and ``boundary_aspect``.
    boundary: tuple[float, float] | None = None
    boundary_aspect: float = 1.4  # length / depth of the derived footprint
    # Deterministic search controls. Same seed + program → identical solution.
    seed: int = 0
    iterations: int = 4000
    # Provenance: non-fatal notes from building the program — e.g. a room whose
    # area the graph didn't state and the adapter had to assume. Surfaced to the
    # caller, never silently applied (docs/how-this-works.md §7).
    warnings: list[str] = Field(default_factory=list)


class PlacedRoom(BaseModel):
    """A room after placement — an axis-aligned rectangle in the floor plane."""

    id: str
    name: str = ""
    x: float       # min corner, x axis (m)
    z: float       # min corner, z axis (m)
    length: float  # x extent (m)
    width: float   # z extent (m)

    @property
    def area(self) -> float:
        return self.length * self.width

    @property
    def aspect(self) -> float:
        lo, hi = sorted((self.length, self.width))
        return hi / lo if lo > 0 else float("inf")


class LayoutSolution(BaseModel):
    """The solved plan plus the diagnostics a caller (or the UI) needs."""

    rooms: list[PlacedRoom]
    boundary: tuple[float, float]
    satisfied_adjacencies: list[tuple[str, str]] = Field(default_factory=list)
    unsatisfied_adjacencies: list[tuple[str, str]] = Field(default_factory=list)
    energy: float = 0.0
    # max relative area error across rooms (|actual-target|/target). ~0 by
    # construction — reported so a caller can assert the invariant held.
    max_area_error: float = 0.0
    iterations: int = 0
    # Carried through from the program (e.g. assumed room areas) so callers /
    # the UI can flag a plan that rests on invented inputs rather than the brief.
    warnings: list[str] = Field(default_factory=list)

    @property
    def adjacency_satisfaction(self) -> float:
        total = len(self.satisfied_adjacencies) + len(self.unsatisfied_adjacencies)
        return 1.0 if total == 0 else len(self.satisfied_adjacencies) / total
