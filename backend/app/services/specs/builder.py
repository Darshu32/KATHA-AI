"""Spec bundle builder — orchestrates every spec generator into one payload.

The exporters consume this dict; the `/specs` API returns it verbatim.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services.specs import material_spec, manufacturing_spec, mep_spec

logger = logging.getLogger(__name__)


def build_spec_bundle(graph: dict, *, project_name: str = "KATHA Project") -> dict:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0]
    dims = room.get("dimensions") or {}
    style = (graph.get("style") or {}).get("primary", "—")

    return {
        "meta": {
            "project_name": project_name,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "room_type": room.get("type", "—"),
            "theme": style,
            "dimensions_m": {
                "length": dims.get("length"),
                "width": dims.get("width"),
                "height": dims.get("height"),
            },
        },
        "material": material_spec.build(graph),
        "manufacturing": manufacturing_spec.build(graph),
        "mep": mep_spec.build(graph),
        "cost": _extract_cost(graph),
        "objects_count": len(graph.get("objects", [])),
    }


def _extract_cost(graph: dict) -> dict:
    estimation = graph.get("estimation") or {}
    # Default to whatever estimation engine recorded; exporters can reformat.
    return {
        "status": estimation.get("status", "pending"),
        "currency": estimation.get("currency", "INR"),
        "line_items": estimation.get("lineItems") or estimation.get("line_items") or [],
        "totals": {
            "low": estimation.get("totalLow") or estimation.get("total_low"),
            "high": estimation.get("totalHigh") or estimation.get("total_high"),
            "base": estimation.get("total") or estimation.get("totalBase"),
        },
        "assumptions": estimation.get("assumptions") or [],
    }
