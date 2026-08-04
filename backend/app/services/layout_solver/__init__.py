"""Deterministic multi-room floor-plan layout solver.

Program (rooms + target areas + required adjacencies) → a set of non-overlapping
room rectangles that tile a boundary. Slicing-tree representation makes non-
overlap / exact tiling / exact area invariant by construction; simulated
annealing tunes proportion and adjacency on top. Pure Python, no LLM, no
dataset, seeded and reproducible.

See ``docs/how-this-works.md`` §4 (layout generation) and §8 (spec-first).
"""

from __future__ import annotations

from .adapter import apply_layout_to_graph, program_from_graph
from .models import LayoutProgram, LayoutSolution, PlacedRoom, RoomSpec
from .pipeline import maybe_solve_layout
from .solver import solve_layout
from .typed import placements_from_solution

__all__ = [
    "RoomSpec",
    "LayoutProgram",
    "PlacedRoom",
    "LayoutSolution",
    "solve_layout",
    "program_from_graph",
    "apply_layout_to_graph",
    "placements_from_solution",
    "maybe_solve_layout",
]
