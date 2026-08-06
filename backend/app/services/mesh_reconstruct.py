"""Tier 2 of upload → geometry: imported mesh → editable parametric part graph.

Tier 1 renders an imported mesh as one static blob. Tier 2 decomposes it into
connected-component PARTS (mesh_geometry.decompose_mesh) and builds a
``DesignGraph`` where each part is an editable object (position + size + type).
That converts a static import into an editable multi-part design that flows into
the edit loop, per-part hotspots, IFC elements, and the spec-sheet BOM.

Scope (v1): decomposition = connected components (a welded single-mesh model is
one part). True architectural reconstruction — wall/room/opening extraction from
a triangle soup — is the deeper Tier 2b.
"""

from __future__ import annotations

from app.models.design_graph import AssetBundle, DesignGraph, SiteInfo, StyleProfile
from app.services.importers.mesh_geometry import decompose_mesh


def reconstruct_graph(parts: list[dict], project_id: str, style: str | None = None) -> dict:
    """Decomposed parts → an editable ``DesignGraph`` (each part an object with a
    position + dimensions + type). design_type = product (object scale) or
    architecture (building scale)."""
    objects: list[dict] = []
    for p in parts:
        objects.append({
            "id": p["id"],
            "type": p.get("type") or "part",
            "name": str(p.get("type") or "part").replace("_", " ").title(),
            "position": p["position"],
            "dimensions": p["dimensions"],
            "material": "imported",
            "role": "imported_part",
        })
    longest = max(
        (max(o["dimensions"]["length"], o["dimensions"]["height"], o["dimensions"]["width"])
         for o in objects),
        default=1.0,
    )
    design_type = "product" if longest < 3.0 else "architecture"
    graph = DesignGraph(
        project_id=project_id, version=1, design_type=design_type,
        style=StyleProfile(primary=style or "modern", secondary=[]),
        site=SiteInfo(unit="metric"), spaces=[], adjacencies=[], geometry=[],
        objects=objects, materials=[], lighting=[],
        constraints=[{"id": "reconstructed_from", "type": "import_meta", "value": "3d_mesh"}],
        estimation={"status": "pending",
                    "assumptions": [f"Reconstructed from an imported mesh — {len(objects)} editable part(s)."]},
        assets=AssetBundle(render_2d=[], scene_3d=[], masks=[],
                           render_prompt_2d="", render_prompt_3d=""),
    )
    return graph.model_dump()


def reconstruct_from_mesh(verts, tris, project_id: str, style: str | None = None) -> tuple[dict, list[dict]]:
    """Mesh → (editable graph, parts). Parts keep their verts/tris for rendering;
    the graph carries only the editable bbox objects."""
    parts = decompose_mesh(verts, tris)
    graph = reconstruct_graph(parts, project_id, style)
    return graph, parts
