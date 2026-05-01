"""Stage 11 — decisions + challenges HTTP surface.

Three routes that mirror the agent-tool surface for callers (UI,
external systems) that don't go through the agent loop:

- ``GET  /projects/{project_id}/decisions`` — list decisions
- ``GET  /projects/{project_id}/decisions/{decision_id}`` — explain
- ``POST /projects/{project_id}/decisions/{decision_id}/challenge``
  — file a challenge

Owner-guarded — every route checks the actor owns the project. Cross-
owner access returns 404 (same shape as 'not found') so existence
isn't leaked, matching the Stage 8 pattern.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import (
    DecisionChallenge,
    DesignDecision,
    Project,
    User,
)
from app.repositories.decisions import (
    DecisionChallengeRepository,
    DesignDecisionRepository,
)


router = APIRouter(
    prefix="/projects",
    tags=["decisions"],
)


_RESOLUTIONS = {
    "rejected_challenge",
    "decision_revised",
    "accepted_override",
}


# ─────────────────────────────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────────────────────────────


class DecisionItem(BaseModel):
    id: str
    project_id: str
    actor_id: Optional[str] = None
    version: int
    category: str
    title: str
    summary: str
    rationale: str = ""
    rejected_alternatives: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at: Optional[str] = None
    reasoning_steps: list[dict[str, Any]] = Field(default_factory=list)
    confidence_score: Optional[float] = None
    confidence_factors: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class ChallengeItem(BaseModel):
    id: str
    decision_id: str
    project_id: str
    challenger_id: Optional[str] = None
    challenge_text: str
    resolution: str
    response_reasoning: str = ""
    new_decision_id: Optional[str] = None
    created_at: Optional[str] = None


class DecisionListOut(BaseModel):
    project_id: str
    total: int
    decisions: list[DecisionItem] = Field(default_factory=list)


class DecisionDetailOut(BaseModel):
    decision: DecisionItem
    challenges: list[ChallengeItem] = Field(default_factory=list)


class FileChallengeIn(BaseModel):
    challenge_text: str = Field(min_length=4, max_length=2000)
    resolution: Optional[str] = Field(default=None)
    response_reasoning: str = Field(default="", max_length=4000)
    new_decision_id: Optional[str] = Field(default=None, max_length=64)

    @field_validator("resolution")
    @classmethod
    def _check_resolution(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        if v not in _RESOLUTIONS:
            raise ValueError(
                f"resolution must be one of {sorted(_RESOLUTIONS)}; got {v!r}"
            )
        return v


class FileChallengeOut(BaseModel):
    challenge: ChallengeItem


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _decision_to_item(row: DesignDecision) -> DecisionItem:
    created = getattr(row, "created_at", None)
    score = getattr(row, "confidence_score", None)
    return DecisionItem(
        id=str(row.id),
        project_id=str(row.project_id),
        actor_id=row.actor_id,
        version=int(row.version or 0),
        category=row.category or "general",
        title=row.title or "",
        summary=row.summary or "",
        rationale=row.rationale or "",
        rejected_alternatives=list(row.rejected_alternatives or []),
        sources=list(row.sources or []),
        tags=list(row.tags or []),
        created_at=(
            created.isoformat() if hasattr(created, "isoformat") else None
        ),
        reasoning_steps=list(getattr(row, "reasoning_steps", None) or []),
        confidence_score=float(score) if score is not None else None,
        confidence_factors=list(getattr(row, "confidence_factors", None) or []),
        provenance=dict(getattr(row, "provenance", None) or {}),
    )


def _challenge_to_item(row: DecisionChallenge) -> ChallengeItem:
    created = getattr(row, "created_at", None)
    return ChallengeItem(
        id=str(row.id),
        decision_id=str(row.decision_id),
        project_id=str(row.project_id),
        challenger_id=row.challenger_id,
        challenge_text=row.challenge_text or "",
        resolution=row.resolution or "pending",
        response_reasoning=row.response_reasoning or "",
        new_decision_id=row.new_decision_id,
        created_at=(
            created.isoformat() if hasattr(created, "isoformat") else None
        ),
    )


async def _ensure_owner_project(
    db: AsyncSession, *, project_id: str, owner_id: str,
) -> Project:
    project = await db.get(Project, project_id)
    if project is None or project.owner_id != owner_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


# ─────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────


@router.get(
    "/{project_id}/decisions",
    response_model=DecisionListOut,
)
async def list_decisions_route(
    project_id: str,
    category: Optional[str] = Query(default=None, max_length=64),
    version: Optional[int] = Query(default=None, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DecisionListOut:
    """Return the full design-decision log for one project."""
    await _ensure_owner_project(db, project_id=project_id, owner_id=user.id)

    rows = await DesignDecisionRepository.list_for_project(
        db,
        project_id=project_id,
        category=category,
        version=version,
        limit=limit,
    )
    total = await DesignDecisionRepository.count_for_project(
        db, project_id=project_id,
    )
    return DecisionListOut(
        project_id=project_id,
        total=total,
        decisions=[_decision_to_item(r) for r in rows],
    )


@router.get(
    "/{project_id}/decisions/{decision_id}",
    response_model=DecisionDetailOut,
)
async def get_decision_route(
    project_id: str,
    decision_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DecisionDetailOut:
    """Walk back one decision in full — record + challenge chain."""
    await _ensure_owner_project(db, project_id=project_id, owner_id=user.id)

    row = await DesignDecisionRepository.get_by_id(
        db, decision_id=decision_id,
    )
    if row is None or row.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Decision not found",
        )
    challenges = await DecisionChallengeRepository.list_for_decision(
        db, decision_id=decision_id, limit=50,
    )
    return DecisionDetailOut(
        decision=_decision_to_item(row),
        challenges=[_challenge_to_item(c) for c in challenges],
    )


@router.post(
    "/{project_id}/decisions/{decision_id}/challenge",
    response_model=FileChallengeOut,
    status_code=status.HTTP_201_CREATED,
)
async def file_challenge_route(
    project_id: str,
    decision_id: str,
    payload: FileChallengeIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FileChallengeOut:
    """File a challenge against a recorded decision.

    The architect can challenge any past decision. If they already
    know the resolution (e.g. UI flow where the user clicked
    "accept anyway") they can pass ``resolution`` +
    ``response_reasoning`` atomically. Otherwise the challenge is
    filed in ``pending`` and the agent (or a subsequent UI step)
    resolves it later.
    """
    await _ensure_owner_project(db, project_id=project_id, owner_id=user.id)

    target = await DesignDecisionRepository.get_by_id(
        db, decision_id=decision_id,
    )
    if target is None or target.project_id != project_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Decision not found",
        )

    if payload.new_decision_id:
        new_target = await DesignDecisionRepository.get_by_id(
            db, decision_id=payload.new_decision_id,
        )
        if new_target is None or new_target.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="new_decision_id not in this project",
            )

    if payload.resolution and not payload.response_reasoning.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="response_reasoning is required when resolution is set",
        )

    row = await DecisionChallengeRepository.file_challenge(
        db,
        project_id=project_id,
        decision_id=decision_id,
        challenger_id=user.id,
        challenge_text=payload.challenge_text,
        extra={"filed_via": "http_route"},
    )
    if payload.resolution:
        row = await DecisionChallengeRepository.resolve(
            db,
            challenge_id=row.id,
            resolution=payload.resolution,
            response_reasoning=payload.response_reasoning,
            new_decision_id=payload.new_decision_id,
        )
    await db.commit()
    return FileChallengeOut(challenge=_challenge_to_item(row))
