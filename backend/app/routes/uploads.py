"""Stage 7 — multi-modal upload routes.

Three endpoints:

- ``POST /v2/uploads`` — multipart form upload. Returns the new
  asset's id, kind, mime_type, size, and a content URL.
- ``GET /v2/uploads/{asset_id}/content`` — proxy the bytes through
  FastAPI. Used in dev (local storage) and as a fallback when the
  storage backend can't generate a presigned URL.
- ``DELETE /v2/uploads/{asset_id}`` — remove the row + the stored
  bytes. Owner-guarded.

All three are owner-scoped — users only see / delete their own
uploads.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import ErrorResponse
from app.repositories.uploads import UploadRepository
from app.storage import StorageError, get_storage_backend

log = logging.getLogger(__name__)

router = APIRouter(prefix="/v2", tags=["uploads"])


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _content_url(asset_id: str) -> str:
    """The proxy URL clients use when no presigned URL is available."""
    return f"/api/v1/v2/uploads/{asset_id}/content"


def _safe_extension(filename: str, mime: str) -> str:
    """Pick a stable, lowercase extension for the storage key.

    We trust the MIME type more than the filename — a client could
    upload "evil.exe" claiming to be ``image/png``; we just key the
    storage path on the MIME-derived suffix and the assigned id.
    """
    mime = (mime or "").lower()
    by_mime = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/heic": "heic",
        "image/heif": "heif",
    }
    if mime in by_mime:
        return by_mime[mime]
    # Fall back to a sanitised filename suffix.
    name = (filename or "").lower()
    if "." in name:
        suf = name.rsplit(".", 1)[-1]
        # Strip everything except [a-z0-9].
        suf = "".join(ch for ch in suf if ch.isalnum())[:8]
        if suf:
            return suf
    return "bin"


# ─────────────────────────────────────────────────────────────────────
# POST /v2/uploads
# ─────────────────────────────────────────────────────────────────────


@router.post("/uploads")
async def upload_asset(
    file: UploadFile = File(..., description="Image file (jpg/png/webp/heic/heif)"),
    kind: str = Form(
        default="image",
        description=(
            "Asset purpose — image | site_photo | reference | mood_board | "
            "hand_sketch | existing_floor_plan. Drives the vision tool's "
            "prompt selection downstream."
        ),
    ),
    project_id: Optional[str] = Form(
        default=None,
        description="Optional project scope. When omitted the asset is "
                    "owner-scoped only.",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    settings = get_settings()

    # 1. Validate MIME type.
    mime = (file.content_type or "").lower()
    if mime not in settings.upload_allowed_mime:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=ErrorResponse(
                error="unsupported_mime",
                message=(
                    f"MIME type {mime!r} not allowed. Accepted: "
                    f"{', '.join(settings.upload_allowed_mime)}."
                ),
            ).model_dump(),
        )

    # 2. Read bytes (FastAPI buffers <1 MB in memory; larger files
    # spool to a temp file). We hash on the way in for content
    # de-dup / audit purposes.
    payload = await file.read()
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ErrorResponse(
                error="empty_file",
                message="Uploaded file is empty.",
            ).model_dump(),
        )
    if len(payload) > settings.upload_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=ErrorResponse(
                error="too_large",
                message=(
                    f"File is {len(payload)} bytes; cap is "
                    f"{settings.upload_max_bytes}."
                ),
            ).model_dump(),
        )

    digest = hashlib.sha256(payload).hexdigest()

    # 3. Build a stable storage key — yyyymmdd / owner / random / id.ext.
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand = secrets.token_hex(8)
    suffix = _safe_extension(file.filename or "", mime)
    storage_key = f"uploads/{today}/{user.id}/{rand}.{suffix}"

    backend = get_storage_backend()

    # 4. Insert the row in 'uploading' state so we have an id, then
    # write the bytes, then flip to 'ready'. If the bytes write
    # fails we mark 'error' so the admin UI can show what went wrong.
    row = await UploadRepository.create(
        db,
        owner_id=user.id,
        project_id=project_id,
        kind=kind or "image",
        storage_backend=backend.name,
        storage_key=storage_key,
        original_filename=file.filename or "",
        mime_type=mime,
        size_bytes=len(payload),
        content_hash=digest,
        status="uploading",
        metadata={"sha256": digest},
    )

    try:
        await backend.put_bytes(
            key=storage_key, data=payload, mime_type=mime,
        )
    except StorageError as exc:
        await UploadRepository.mark_status(
            db, asset_id=row.id, status="error", error_message=str(exc),
        )
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ErrorResponse(
                error="storage_unavailable",
                message=str(exc),
            ).model_dump(),
        ) from exc

    await UploadRepository.mark_status(
        db, asset_id=row.id, status="ready",
    )
    await db.commit()

    presigned = await backend.presigned_url(storage_key, expires_seconds=3600)

    return {
        "id": row.id,
        "kind": row.kind,
        "mime_type": row.mime_type,
        "size_bytes": row.size_bytes,
        "content_hash": row.content_hash,
        "storage_backend": row.storage_backend,
        "status": row.status,
        "content_url": _content_url(row.id),
        "presigned_url": presigned,
        "created_at": row.created_at.isoformat()
            if hasattr(row.created_at, "isoformat") else None,
    }


# ─────────────────────────────────────────────────────────────────────
# GET /v2/uploads/{id}/content — proxy bytes
# ─────────────────────────────────────────────────────────────────────


@router.get("/uploads/{asset_id}/content")
async def get_asset_content(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Proxy the bytes through FastAPI.

    Used in dev (local storage has no presigned URLs) and as a
    fallback when the storage backend can't presign. The owner check
    happens at the DB layer — cross-owner reads return 404.
    """
    row = await UploadRepository.get_for_owner(
        db, asset_id=asset_id, owner_id=user.id,
    )
    if row is None or row.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="not_found",
                message="Upload not found or not ready.",
            ).model_dump(),
        )

    backend = get_storage_backend()
    try:
        body = await backend.get_bytes(row.storage_key)
    except StorageError as exc:
        log.warning("storage read failed for %s: %s", asset_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=ErrorResponse(
                error="storage_unavailable",
                message=str(exc),
            ).model_dump(),
        ) from exc

    headers = {
        "Cache-Control": "private, max-age=300",
        "Content-Length": str(len(body)),
    }
    return Response(content=body, media_type=row.mime_type, headers=headers)


# ─────────────────────────────────────────────────────────────────────
# DELETE /v2/uploads/{id}
# ─────────────────────────────────────────────────────────────────────


@router.delete(
    "/uploads/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_asset(
    asset_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    row = await UploadRepository.delete_for_owner(
        db, asset_id=asset_id, owner_id=user.id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ErrorResponse(
                error="not_found",
                message="Upload not found.",
            ).model_dump(),
        )

    # Bytes cleanup is best-effort — we already removed the DB row.
    backend = get_storage_backend()
    try:
        await backend.delete(row.storage_key)
    except StorageError as exc:  # noqa: BLE001
        log.warning(
            "storage delete failed for %s (%s): %s — DB row already removed",
            asset_id, row.storage_key, exc,
        )

    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────────
# GET /v2/uploads — list owner's uploads
# ─────────────────────────────────────────────────────────────────────


@router.get("/uploads")
async def list_assets(
    project_id: Optional[str] = None,
    kind: Optional[str] = None,
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    rows = await UploadRepository.list_for_owner(
        db,
        owner_id=user.id,
        project_id=project_id,
        kind=kind,
        status="ready",
        limit=limit,
    )
    return {
        "count": len(rows),
        "uploads": [
            {
                "id": r.id,
                "kind": r.kind,
                "mime_type": r.mime_type,
                "size_bytes": r.size_bytes,
                "original_filename": r.original_filename,
                "project_id": r.project_id,
                "status": r.status,
                "content_url": _content_url(r.id),
                "created_at": r.created_at.isoformat()
                    if hasattr(r.created_at, "isoformat") else None,
            }
            for r in rows
        ],
    }
