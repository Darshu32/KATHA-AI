"""Interop exports — the distribution wedge out of KATHA into AEC tooling.

Speckle is the first target: the design's real kernel geometry becomes a Speckle
object tree that Revit / Rhino / Grasshopper / ArchiCAD read natively. The export
always serializes offline (proving the geometry is genuine); the live server push
is config-gated on SPECKLE_* settings.
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.services.design_graph_service import get_latest_version, get_project
from app.services.spatial.speckle_export import (
    build_speckle_base,
    send_to_speckle,
    serialize_base,
)

router = APIRouter(prefix="/projects/{project_id}/export", tags=["exports"])


def _check_owner(project, user: User):
    if project is None or project.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


def _triangle_count(root) -> int:
    return sum(mesh.faces.count(3) for e in root["@elements"] for mesh in e["@displayValue"])


@router.get("/speckle")
async def export_speckle(
    project_id: str,
    push: bool = Query(False, description="Push to the configured Speckle server (needs SPECKLE_* settings)."),
    format: str = Query("summary", pattern="^(summary|objects)$"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Export the design as a Speckle object tree.

    - ``format=summary`` (default): JSON — object/triangle counts, root hash, and
      whether a live push is configured (and its result when ``push=true``).
    - ``format=objects``: the serialized Speckle object tree as a downloadable
      ``.json`` (the exact payload a transport would upload) — works fully offline.
    """
    project = await get_project(db, project_id)
    _check_owner(project, user)
    version = await get_latest_version(db, project_id)
    if version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No versions found")

    try:
        root = build_speckle_base(version.graph_data or {}, project.name or "KATHA design")
        root_hash, root_obj = serialize_base(root)
    except Exception as exc:  # noqa: BLE001 — export must never hard-500 the app
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Speckle export failed") from exc

    if format == "objects":
        safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in (project.name or "design"))
        return Response(
            content=json.dumps(root_obj),
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{safe}.speckle.json"',
                "Cache-Control": "no-store",
            },
        )

    s = get_settings()
    configured = bool(s.speckle_token and s.speckle_server_url and s.speckle_project_id)
    pushed = None
    if push:
        if not configured:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Speckle push not configured — set SPECKLE_SERVER_URL / SPECKLE_TOKEN / SPECKLE_PROJECT_ID",
            )
        pushed = send_to_speckle(
            root,
            token=s.speckle_token,
            server=s.speckle_server_url,
            project_id=s.speckle_project_id,
            message=f"KATHA export — {project.name} v{version.version}",
        )
        if pushed is None:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Speckle push failed")

    return {
        "project_id": project_id,
        "version": version.version,
        "root_hash": root_hash,
        "object_count": len(root["@elements"]),
        "triangle_count": _triangle_count(root),
        "units": "m",
        "coordinate_system": "z-up",
        "push_configured": configured,
        "pushed": pushed,
    }
