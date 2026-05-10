"""Object-storage HTTP surface — streams stored renders to the frontend.

The image-generation pipeline writes generated PNGs to local filesystem
storage via :mod:`app.services.storage`. The DB stores only the key;
the frontend fetches the bytes through this route.

Why a path-style key
--------------------
Keys look like ``renders/{project_id}/v{n}-{uuid}.png`` so a manual
filesystem inspection mirrors the logical hierarchy. Path-traversal
attacks are blocked inside ``storage._resolve_safe`` — the route
itself doesn't need extra hardening beyond that.

Cache headers
-------------
The UUID suffix in each key makes the object immutable: same key →
same bytes forever. We set ``Cache-Control: immutable`` with a long
max-age so a browser / CDN serving a stable URL never re-fetches.
"""

from __future__ import annotations

import logging
import mimetypes

from fastapi import APIRouter, HTTPException, Response, status

from app.services.storage import read_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("/{key:path}")
async def get_asset(key: str) -> Response:
    """Stream the bytes at ``key`` or return 404 if absent."""
    data = await read_bytes(key)
    if data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No asset for key {key!r}",
        )
    mime, _ = mimetypes.guess_type(key)
    return Response(
        content=data,
        media_type=mime or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
