"""Fidelity verification for the architectural working views.

Two different questions get conflated when someone asks "are these drawings
correct?":

  1. **Fidelity** — does each view faithfully depict *the design graph the user
     generated*? Every object in the design appears in every relevant view; the
     dimensions annotated on the drawing equal the dimensions in the graph.
     This is a pure data question — *software-checkable*, no architectural
     judgement required.

  2. **Architectural soundness** — is the design itself buildable / to-code?
     That's a domain question handled elsewhere (knowledge/precision
     validators, NBC, ergonomics).

This module answers **(1)**. Each renderer in ``architectural_views_service``
emits a ``placements`` manifest — the exact list of objects it drew. Here we
cross-check those manifests against the graph's own object set and the
annotated dimensions against the graph's room envelope, then return a plain
report a non-architect can read: "every object you designed shows up in every
view, and every dimension on the drawing matches your design."
"""

from __future__ import annotations

from typing import Callable

from app.services.architectural_views_service import (
    generate_detail_package,
    generate_elevation_package,
    generate_isometric_package,
    generate_section_package,
    _objects,
    _obj_box,
    _room,
)

# Views that depict individual design objects (the detail sheet draws generic
# construction junctions, not the user's objects, so it is coverage-exempt).
_OBJECT_VIEWS: dict[str, Callable[[dict], dict]] = {
    "section_view": generate_section_package,
    "elevation_view": generate_elevation_package,
    "isometric_view": generate_isometric_package,
}

# Walls form the room shell and are drawn as the envelope, not as placed
# objects, so they are excluded from the per-object coverage expectation.
_NON_DEPICTED_ROLES = {"wall"}

# Tolerance for comparing an annotated dimension against the graph value.
_DIM_TOL = 0.01


def _expected_object_ids(graph: dict) -> set[str]:
    ids: set[str] = set()
    for raw in _objects(graph):
        box = _obj_box(raw)
        if box["role"] in _NON_DEPICTED_ROLES:
            continue
        ids.add(box["id"])
    return ids


def _dimension_checks(view_type: str, summary: dict, room: tuple[float, float, float]) -> list[dict]:
    """Compare dimensions the drawing annotates against the graph room."""
    L, W, H = room
    expected: dict[str, dict[str, float]] = {
        "section_view": {"ceiling_height_m": H},
        "elevation_view": {"wall_length_m": L, "wall_height_m": H},
        "isometric_view": {"length_m": L, "width_m": W, "height_m": H},
    }.get(view_type, {})

    checks: list[dict] = []
    for key, graph_value in expected.items():
        drawn = summary.get(key)
        ok = isinstance(drawn, (int, float)) and abs(float(drawn) - graph_value) <= _DIM_TOL
        checks.append(
            {
                "dimension": key,
                "drawn": drawn,
                "graph": round(graph_value, 2),
                "ok": bool(ok),
            }
        )
    return checks


def verify_view(view_type: str, graph: dict) -> dict:
    """Verify a single view's fidelity against the graph."""
    generator = _OBJECT_VIEWS.get(view_type)
    if generator is None:
        raise ValueError(f"Unknown object view: {view_type}")

    package = generator(graph)
    placements = package.get("placements") or []
    placed_ids = {p["id"] for p in placements if isinstance(p, dict) and p.get("id")}
    expected = _expected_object_ids(graph)

    missing = sorted(expected - placed_ids)   # in design but not drawn
    extra = sorted(placed_ids - expected)     # drawn but not in design

    dim_checks = _dimension_checks(view_type, package.get("summary") or {}, _room(graph))

    return {
        "view": view_type,
        "objects_in_design": len(expected),
        "objects_drawn": len(placed_ids),
        "missing_from_view": missing,
        "not_in_design": extra,
        "dimension_checks": dim_checks,
        "ok": not missing and not extra and all(c["ok"] for c in dim_checks),
    }


def verify_graph_views(graph: dict) -> dict:
    """Verify every object-depicting view; return an aggregate fidelity report."""
    views = [verify_view(name, graph) for name in _OBJECT_VIEWS]
    # The detail sheet is generated for completeness but is coverage-exempt.
    detail = generate_detail_package(graph)
    return {
        "ok": all(v["ok"] for v in views),
        "object_count": len(_expected_object_ids(graph)),
        "views": views,
        "detail_sheet": {
            "drawing_type": detail.get("drawing_type"),
            "materials_cited": (detail.get("summary") or {}).get("materials_cited", []),
            "coverage_exempt": True,
        },
    }


def format_fidelity_report(report: dict) -> str:
    """Render a fidelity report as a human-readable table (for CLI / logs)."""
    lines = [
        f"Design objects depicted: {report['object_count']}",
        f"Overall fidelity: {'PASS ✓' if report['ok'] else 'FAIL ✗'}",
        "",
        f"{'View':<16}{'Drawn/Total':<13}{'Result':<8}{'Dimensions match graph'}",
        f"{'-'*16}{'-'*13}{'-'*8}{'-'*36}",
    ]
    for v in report["views"]:
        drawn = f"{v['objects_drawn']}/{v['objects_in_design']}"
        dims = ", ".join(
            f"{c['dimension'].split('_m')[0]} {'✓' if c['ok'] else '✗'}"
            for c in v["dimension_checks"]
        ) or "—"
        result = "PASS" if v["ok"] else "FAIL"
        lines.append(f"{v['view']:<16}{drawn:<13}{result:<8}{dims}")
        if v["missing_from_view"]:
            lines.append(f"    missing: {', '.join(v['missing_from_view'])}")
        if v["not_in_design"]:
            lines.append(f"    phantom: {', '.join(v['not_in_design'])}")
    return "\n".join(lines)
