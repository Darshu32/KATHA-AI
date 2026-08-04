"""Pipeline seam — solve a multi-room program when the graph carries one.

Wired into the initial-generation pipeline (``generation_pipeline``). It fires
only when the graph is a genuine, unplaced multi-room program — two or more
spaces, none yet positioned — so today's single-room graphs (the LLM emits one
space) pass through untouched. When graph generation starts emitting multi-room
programs, floor-plan solving turns on here automatically, with no further wiring.

Deliberately conservative: any doubt (one room, already placed, malformed) →
return the graph unchanged. Never raises — a solver hiccup must not break
generation.
"""

from __future__ import annotations

import logging

from .adapter import apply_layout_to_graph, program_from_graph
from .models import LayoutSolution
from .solver import solve_layout

logger = logging.getLogger(__name__)


def _already_placed(graph: dict) -> bool:
    """True if any space already carries a position (don't re-solve a placed plan)."""
    for s in graph.get("spaces") or []:
        if isinstance(s, dict) and isinstance(s.get("position"), dict):
            return True
    return False


def maybe_solve_layout(graph: dict) -> tuple[dict, LayoutSolution | None]:
    """Solve + place rooms iff ``graph`` is an unplaced multi-room program.

    Returns ``(graph, solution)`` — the graph updated with room positions +
    dimensions and the :class:`LayoutSolution` when it solved, or the original
    graph and ``None`` when there was nothing to do.
    """
    spaces = graph.get("spaces") if isinstance(graph, dict) else None
    if not isinstance(spaces, list) or len(spaces) < 2:
        return graph, None            # single room / no program → nothing to solve
    if _already_placed(graph):
        return graph, None            # already positioned → don't re-solve

    try:
        program = program_from_graph(graph)
        if len(program.rooms) < 2:
            return graph, None
        solution = solve_layout(program)
        applied = apply_layout_to_graph(graph, solution)
        logger.info(
            "layout_solved rooms=%d adjacency=%.0f%% area_err=%.1e",
            len(solution.rooms),
            100 * solution.adjacency_satisfaction,
            solution.max_area_error,
        )
        return applied, solution
    except Exception as exc:  # noqa: BLE001 — never break generation
        logger.warning("layout solve skipped: %s", exc)
        return graph, None
