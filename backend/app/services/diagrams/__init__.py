"""Auto-diagram registry — BRD Layer 2B.

Public API:
    generate_all(graph) -> list[dict]   # runs every registered diagram
    generate_one(graph, diagram_id) -> dict | None
    list_available() -> list[dict]      # id + human name

Each diagram module exposes a `generate(graph, **kwargs) -> dict` returning:
    { id, name, format, svg, meta }
"""

from __future__ import annotations

import logging

from app.services.diagrams import (
    concept_transparency,
    design_process,
    form_development,
    hierarchy,
    massing,
    solid_void,
    spatial_organism,
    volumetric,
)

logger = logging.getLogger(__name__)

_REGISTRY = {
    "concept_transparency": concept_transparency,
    "form_development": form_development,
    "massing": massing,
    "volumetric": volumetric,
    "design_process": design_process,
    "solid_void": solid_void,
    "spatial_organism": spatial_organism,
    "hierarchy": hierarchy,
}

_PLANNED: list[tuple[str, str]] = []  # all 8 now ready


def generate_all(graph: dict) -> list[dict]:
    results: list[dict] = []
    for diagram_id, module in _REGISTRY.items():
        try:
            results.append(module.generate(graph))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("diagram_failed", extra={"id": diagram_id, "error": str(exc)})
            results.append({"id": diagram_id, "error": str(exc)})
    return results


def generate_one(graph: dict, diagram_id: str) -> dict | None:
    module = _REGISTRY.get(diagram_id)
    if not module:
        return None
    try:
        return module.generate(graph)
    except Exception as exc:  # pragma: no cover
        logger.warning("diagram_failed", extra={"id": diagram_id, "error": str(exc)})
        return {"id": diagram_id, "error": str(exc)}


def list_available() -> list[dict]:
    ready = [{"id": did, "name": _name(did), "status": "ready"} for did in _REGISTRY]
    planned = [{"id": did, "name": name, "status": "planned"} for did, name in _PLANNED]
    return ready + planned


def _name(diagram_id: str) -> str:
    return {
        "concept_transparency": "Concept Transparency",
        "form_development": "Form Development",
        "massing": "Massing",
        "volumetric": "Volumetric",
        "design_process": "Design Process",
        "solid_void": "Solid vs Void",
        "spatial_organism": "Spatial Organism",
        "hierarchy": "Hierarchy",
    }.get(diagram_id, diagram_id)


__all__ = ["generate_all", "generate_one", "list_available"]
