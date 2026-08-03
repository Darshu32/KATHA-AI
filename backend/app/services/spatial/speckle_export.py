"""Speckle export — the distribution wedge into Revit / Rhino / Grasshopper / ArchiCAD.

Turns the design's real kernel solids into a Speckle object tree (a data object
whose ``@elements`` are per-object Bases carrying a ``@displayValue`` Mesh) via
specklepy. Geometry is emitted Z-up (Speckle/AEC convention) from KATHA's Y-up
world. Serialization is verifiable fully offline; the live push to a Speckle
server is config-gated on a token + server + project (SPECKLE_* settings),
mirroring the finish-pass / ControlNet-depth seam.
"""

from __future__ import annotations

import logging

from app.services.spatial.kernel import build_scene

logger = logging.getLogger(__name__)


def _mesh_for(solid):
    """Kernel solid → Speckle Mesh, remapped Y-up (KATHA) → Z-up (Speckle):
    Speckle (X, Y, Z) = KATHA (x, z, y)."""
    from specklepy.objects.geometry import Mesh

    verts: list[float] = []
    for v in solid.verts:
        verts.extend([float(v[0]), float(v[2]), float(v[1])])
    faces: list[int] = []
    for t in solid.tris:
        faces.extend([3, int(t[0]), int(t[1]), int(t[2])])  # 3 = triangle
    return Mesh(vertices=verts, faces=faces, units="m")


def build_speckle_base(graph: dict, name: str = "KATHA design"):
    """Design graph → Speckle root Base (``@elements`` = per-object Bases with a
    ``@displayValue`` mesh — the convention the Speckle viewer + connectors read)."""
    from specklepy.objects import Base

    solids, _bbox, kind = build_scene(graph)
    elements = []
    for s in solids:
        if s.verts is None or not len(s.verts) or s.tris is None or not len(s.tris):
            continue
        obj = Base()
        obj["name"] = s.name or s.id
        obj["objectType"] = s.type
        obj["@displayValue"] = [_mesh_for(s)]
        elements.append(obj)

    root = Base()
    root["name"] = name
    root["kind"] = kind
    root["units"] = "m"
    root["sourceApplication"] = "KATHA AI"
    root["@elements"] = elements
    return root


def serialize_base(base) -> tuple[str, dict]:
    """Serialize to Speckle's object format (hash, root-dict). Offline; used for
    verification and as the payload a transport would upload."""
    from specklepy.serialization.base_object_serializer import BaseObjectSerializer

    return BaseObjectSerializer().traverse_base(base)


def send_to_speckle(base, *, token: str, server: str, project_id: str,
                    branch: str = "main", message: str = "KATHA export") -> dict | None:
    """Push to a Speckle server as a commit/version. Returns commit info, or None
    when unconfigured or the push fails (best-effort — never raises)."""
    if not (token and server and project_id):
        return None
    try:
        from specklepy.api import operations
        from specklepy.api.client import SpeckleClient
        from specklepy.transports.server import ServerTransport

        client = SpeckleClient(host=server)
        client.authenticate_with_token(token)
        transport = ServerTransport(client=client, stream_id=project_id)
        object_id = operations.send(base, [transport])

        commit_id = None
        # commit/version creation moved API surface across specklepy majors; try
        # the common shapes, best-effort.
        try:
            commit_id = client.commit.create(project_id, object_id, branch_name=branch, message=message)
        except Exception:  # noqa: BLE001
            try:
                commit_id = client.commit.create(project_id, object_id, message=message)
            except Exception:  # noqa: BLE001
                commit_id = None
        return {"object_id": object_id, "commit_id": commit_id, "server": server, "project_id": project_id}
    except Exception as exc:  # noqa: BLE001
        logger.warning("Speckle push failed: %s", exc)
        return None
