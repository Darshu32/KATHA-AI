"""Notes routes — per-conversation server-side notebooks (Phase 1).

Endpoints
---------
- ``GET    /notes/sections?conversation_id=…`` — list sections in a notebook
- ``PUT    /notes/sections/{id}``               — upsert a single section
- ``DELETE /notes/sections/{id}``               — delete a single section
- ``POST   /notes/import``                      — bulk import (one-time migration)

All endpoints require auth. Ownership is enforced inside the
repository — the route layer just maps ``None`` results to 404 so we
never reveal whether an ID exists under another account.

Why PUT-upsert instead of POST + PATCH
--------------------------------------
The frontend mints section IDs locally so optimistic UI works. The
client owns the ID; we upsert on it. Two endpoints would buy nothing
and complicate the debounce / retry logic.

Sanity guards
-------------
We cap ``len(blocks)`` per section and the total number of sections
per conversation. Both limits are deliberately *soft* — large
enough that no real notebook hits them, small enough that a buggy
client looping on save can't fill the DB.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.models.schemas import (
    NoteSectionImportRequest,
    NoteSectionImportResult,
    NoteSectionListOut,
    NoteSectionOut,
    NoteSectionUpsert,
)
from app.repositories.notes import NotesRepository

router = APIRouter(prefix="/notes", tags=["notes"])


# Soft caps. Tuned to comfortably exceed real usage while bounding
# the damage a misbehaving client can do per request.
MAX_BLOCKS_PER_SECTION = 500
MAX_SECTIONS_PER_CONVERSATION = 200
MAX_IMPORT_BATCH = 500
MAX_TAGS_PER_SECTION = 20
MAX_TAG_LENGTH = 40


def _sanitize_tags(raw: list[str]) -> list[str]:
    """Trim, drop empties, dedupe (case-insensitive), and cap length.

    Done server-side so the DB never sees junk regardless of client
    behaviour. Tag matching is case-insensitive in the UI, so we
    canonicalise on the way in: lowercase the *first* occurrence of
    each tag's casing wins so users see the form they typed.
    """
    seen: set[str] = set()
    out: list[str] = []
    for t in raw:
        if not isinstance(t, str):
            continue
        trimmed = t.strip()[:MAX_TAG_LENGTH]
        if not trimmed:
            continue
        key = trimmed.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(trimmed)
        if len(out) >= MAX_TAGS_PER_SECTION:
            break
    return out


@router.get("/sections", response_model=NoteSectionListOut)
async def list_sections(
    conversation_id: str = Query(min_length=1, max_length=64),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteSectionListOut:
    """All sections for one conversation's notebook, newest first."""
    rows = await NotesRepository.list_for_conversation(
        db,
        owner_id=user.id,
        conversation_id=conversation_id,
    )
    return NoteSectionListOut(
        sections=[NoteSectionOut.model_validate(r) for r in rows]
    )


@router.put(
    "/sections/{section_id}",
    response_model=NoteSectionOut,
)
async def upsert_section(
    section_id: str,
    payload: NoteSectionUpsert,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteSectionOut:
    """Create or update a section by client-supplied ID.

    See module docstring for why this is PUT-upsert and not POST/PATCH.
    """
    if len(payload.blocks) > MAX_BLOCKS_PER_SECTION:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Section has {len(payload.blocks)} blocks; "
                f"max is {MAX_BLOCKS_PER_SECTION}."
            ),
        )

    # Cap total sections per conversation. We only check on *create*
    # (i.e. when no row exists yet) so existing notebooks aren't
    # locked out from editing if the cap is later lowered.
    existing = await NotesRepository.get_by_id_for_owner(
        db, section_id=section_id, owner_id=user.id
    )
    if existing is None:
        siblings = await NotesRepository.list_for_conversation(
            db, owner_id=user.id, conversation_id=payload.conversation_id
        )
        if len(siblings) >= MAX_SECTIONS_PER_CONVERSATION:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"This conversation already has "
                    f"{MAX_SECTIONS_PER_CONVERSATION} note sections — "
                    f"the cap. Delete some before adding more."
                ),
            )

    row = await NotesRepository.upsert(
        db,
        section_id=section_id,
        owner_id=user.id,
        conversation_id=payload.conversation_id,
        title=payload.title,
        blocks=payload.blocks,
        tags=_sanitize_tags(payload.tags),
        # Pydantic already enforced the 4MB ceiling; we trust it here.
        image_url=payload.image_url,
        source_message_id=payload.source_message_id,
        client_created_at=payload.client_created_at,
    )

    if row is None:
        # The ID exists under a different owner. Surface 404 instead
        # of 403 to avoid leaking that the section exists at all.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note section not found",
        )

    return NoteSectionOut.model_validate(row)


@router.delete(
    "/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_section(
    section_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Delete a section. 204 on success, 404 if it doesn't exist or
    belongs to another user (we don't distinguish — see module docs).
    """
    deleted = await NotesRepository.delete_by_id_for_owner(
        db, section_id=section_id, owner_id=user.id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Note section not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/import", response_model=NoteSectionImportResult)
async def import_sections(
    payload: NoteSectionImportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NoteSectionImportResult:
    """One-time bulk push of localStorage notes to the server.

    Called by the frontend the first time a logged-in user hits the
    new sync layer. Existing IDs are *skipped*, not overwritten — if
    the user already has a server-side version of a section, that's
    the canonical copy.
    """
    if len(payload.sections) > MAX_IMPORT_BATCH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                f"Import batch has {len(payload.sections)} sections; "
                f"max per request is {MAX_IMPORT_BATCH}. Split and retry."
            ),
        )

    # Reject any single section that violates the per-section cap.
    for s in payload.sections:
        if len(s.blocks) > MAX_BLOCKS_PER_SECTION:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=(
                    f"Section {s.id!r} has {len(s.blocks)} blocks; "
                    f"max is {MAX_BLOCKS_PER_SECTION}."
                ),
            )

    # Sanitise tags on the import path too — old localStorage data
    # may carry whitespace or duplicates we'd rather not persist.
    section_dicts = []
    for s in payload.sections:
        d = s.model_dump()
        d["tags"] = _sanitize_tags(d.get("tags") or [])
        section_dicts.append(d)

    imported, skipped = await NotesRepository.import_skip_existing(
        db,
        owner_id=user.id,
        sections=section_dicts,
    )
    return NoteSectionImportResult(imported=imported, skipped=skipped)
