"""Simulated-annealing search over slicing trees.

The slicing-tree representation (``slicing.py``) already guarantees the hard
invariants — non-overlap, exact tiling, exact per-room area. What it does *not*
guarantee is that rooms are well-proportioned or that the requested adjacencies
hold. Those are soft objectives, so we anneal:

    energy = W_ADJ · (unsatisfied adjacencies) + W_ASPECT · Σ sliver penalty

Moves keep every candidate a valid slicing tree (flip a cut, swap two rooms,
mirror a node's children), so the search can never leave the valid region.
Seeded RNG ⇒ identical program + seed ⇒ identical plan (reproducibility is a
first-class property of the spec-first architecture — ``docs/how-this-works.md``
§8).
"""

from __future__ import annotations

import math
import random

from .models import LayoutProgram, LayoutSolution, PlacedRoom
from .slicing import (
    HORIZONTAL,
    VERTICAL,
    Node,
    Rect,
    adjacent,
    clone,
    internals,
    leaves,
    place,
    random_tree,
)

W_ADJ = 10.0      # one missed adjacency dwarfs any proportion cost
W_ASPECT = 1.0

# The solution is kept exact (tiling/area hold to float precision); millimetre
# snapping — the spec-level 1 mm grid of docs/how-this-works.md trap #5 — is
# applied at the boundary, when the adapter writes rooms back into the graph.


def _derive_boundary(program: LayoutProgram) -> tuple[float, float]:
    if program.boundary is not None:
        return program.boundary
    total = sum(r.area for r in program.rooms)
    aspect = max(program.boundary_aspect, 1e-3)
    length = math.sqrt(total * aspect)
    depth = total / length if length > 0 else 0.0
    return (length, depth)


def _aspect_penalty(rect: Rect, max_aspect: float) -> float:
    _, _, length, width = rect
    lo, hi = sorted((length, width))
    if lo <= 0:
        return 100.0  # a degenerate sliver — heavily discouraged
    aspect = hi / lo
    over = aspect - max_aspect
    return over * over if over > 0 else 0.0


def _energy(
    tree: Node,
    boundary: Rect,
    areas: dict[str, float],
    max_aspect: dict[str, float],
    adjacencies: list[tuple[str, str]],
) -> tuple[float, list[tuple[str, str]]]:
    rects = place(tree, boundary, areas)
    aspect_cost = sum(_aspect_penalty(rects[rid], max_aspect[rid]) for rid in rects)
    unsatisfied: list[tuple[str, str]] = []
    for a, b in adjacencies:
        if a in rects and b in rects and adjacent(rects[a], rects[b]):
            continue
        unsatisfied.append((a, b))
    energy = W_ADJ * len(unsatisfied) + W_ASPECT * aspect_cost
    return energy, unsatisfied


def _mutate(tree: Node, rng: random.Random) -> None:
    """Apply one in-place move. Caller passes a clone."""
    move = rng.random()
    nodes_internal = internals(tree)
    if move < 0.45 and nodes_internal:
        node = rng.choice(nodes_internal)          # flip a cut orientation
        node.orient = HORIZONTAL if node.orient == VERTICAL else VERTICAL
    elif move < 0.75 and nodes_internal:
        node = rng.choice(nodes_internal)          # mirror children (reposition)
        node.left, node.right = node.right, node.left
    else:
        lvs = leaves(tree)                          # swap two room assignments
        if len(lvs) >= 2:
            a, b = rng.sample(lvs, 2)
            a.room_id, b.room_id = b.room_id, a.room_id


def solve_layout(program: LayoutProgram) -> LayoutSolution:
    """Solve a program into a placed, non-overlapping floor plan."""
    rooms = program.rooms
    boundary_dims = _derive_boundary(program)
    boundary: Rect = (0.0, 0.0, boundary_dims[0], boundary_dims[1])
    areas = {r.id: r.area for r in rooms}
    max_aspect = {r.id: r.max_aspect for r in rooms}
    adjacencies = [tuple(p) for p in program.adjacencies]
    room_ids = [r.id for r in rooms]
    names = {r.id: r.name for r in rooms}

    # Trivial cases: nothing to search.
    if len(room_ids) <= 1:
        best = random_tree(room_ids, random.Random(program.seed)) if room_ids else None
        rects = place(best, boundary, areas) if best else {}
        return _build_solution(rects, boundary_dims, areas, names, adjacencies, 0.0, 0, program.warnings)

    rng = random.Random(program.seed)
    current = random_tree(room_ids, rng)
    cur_e, _ = _energy(current, boundary, areas, max_aspect, adjacencies)
    best, best_e = clone(current), cur_e

    iterations = max(program.iterations, 1)
    t0 = max(cur_e, 1.0)  # start hot relative to the initial energy
    for i in range(iterations):
        if best_e <= 1e-9:  # perfect: all adjacencies met, no slivers
            break
        temperature = t0 * (1.0 - i / iterations) + 1e-6
        candidate = clone(current)
        _mutate(candidate, rng)
        cand_e, _ = _energy(candidate, boundary, areas, max_aspect, adjacencies)
        if cand_e < cur_e or rng.random() < math.exp(-(cand_e - cur_e) / temperature):
            current, cur_e = candidate, cand_e
            if cand_e < best_e:
                best, best_e = clone(candidate), cand_e

    rects = place(best, boundary, areas)
    return _build_solution(rects, boundary_dims, areas, names, adjacencies, best_e, iterations, program.warnings)


def _build_solution(
    rects: dict[str, Rect],
    boundary_dims: tuple[float, float],
    areas: dict[str, float],
    names: dict[str, str],
    adjacencies: list[tuple[str, str]],
    energy: float,
    iterations: int,
    warnings: list[str] | None = None,
) -> LayoutSolution:
    placed: list[PlacedRoom] = []
    max_area_err = 0.0
    for rid, (x, z, length, width) in rects.items():
        placed.append(
            PlacedRoom(id=rid, name=names.get(rid, ""), x=x, z=z, length=length, width=width)
        )
        target = areas.get(rid, 0.0)
        if target > 0:
            max_area_err = max(max_area_err, abs(length * width - target) / target)

    satisfied: list[tuple[str, str]] = []
    unsatisfied: list[tuple[str, str]] = []
    for a, b in adjacencies:
        ok = a in rects and b in rects and adjacent(rects[a], rects[b])
        (satisfied if ok else unsatisfied).append((a, b))

    return LayoutSolution(
        rooms=placed,
        boundary=boundary_dims,
        satisfied_adjacencies=satisfied,
        unsatisfied_adjacencies=unsatisfied,
        energy=round(energy, 6),
        max_area_error=round(max_area_err, 6),
        iterations=iterations,
        warnings=list(warnings or []),
    )
