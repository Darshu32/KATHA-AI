"""Stage 8 agent tools — architect / client profiles + resume context.

Three read tools:

- :func:`get_architect_fingerprint` — returns the calling user's
  style fingerprint (preferred themes, materials, palette, typical
  room dims, tool-usage patterns). Refreshed nightly by the
  Celery extractor; this tool just reads.
- :func:`get_client_profile` — returns the recurring-constraint
  profile for one of the architect's clients.
- :func:`resume_project_context` — composite read: pulls together
  everything the agent needs to "pick up where we left off" on a
  project — slim graph summary, decisions, project-memory stats,
  recent versions.

All three are read-only (no audit). The system prompt (post-Stage-8B)
will inject the architect fingerprint at session start; until then,
the agent can call ``get_architect_fingerprint`` explicitly when
relevant.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, ToolError, tool
from app.repositories.architects import ArchitectProfileRepository
from app.repositories.clients import (
    ClientProfileRepository,
    ClientRepository,
)
from app.repositories.decisions import DesignDecisionRepository
from app.repositories.project_memory import ProjectMemoryRepository

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# 1. get_architect_fingerprint
# ─────────────────────────────────────────────────────────────────────


class GetArchitectFingerprintInput(BaseModel):
    """No fields — the user is read off ``ctx.actor_id``."""


class ArchitectFingerprintOutput(BaseModel):
    user_id: str
    learning_enabled: bool
    profile_exists: bool
    project_count: int = 0
    preferred_themes: list[dict[str, Any]] = Field(default_factory=list)
    preferred_materials: list[dict[str, Any]] = Field(default_factory=list)
    preferred_palette_hexes: list[str] = Field(default_factory=list)
    typical_room_dimensions_m: dict[str, Any] = Field(default_factory=dict)
    tool_usage: list[dict[str, Any]] = Field(default_factory=list)
    last_project_at: Optional[str] = None
    last_extracted_at: Optional[str] = None


@tool(
    name="get_architect_fingerprint",
    description=(
        "Return the calling architect's style fingerprint — preferred "
        "themes, materials, palette hex codes, typical room "
        "dimensions, tool-usage patterns. Refreshed nightly by the "
        "extractor; this tool just reads. Use to anchor defaults when "
        "starting a fresh project ('the architect prefers walnut + "
        "brass; reach for those first'). Read-only."
    ),
    timeout_seconds=15.0,
)
async def get_architect_fingerprint(
    ctx: ToolContext,
    input: GetArchitectFingerprintInput,
) -> ArchitectFingerprintOutput:
    if not ctx.actor_id:
        raise ToolError(
            "No actor_id on the agent context. The fingerprint tool "
            "requires an authenticated user."
        )

    # Privacy: read the User row to surface ``learning_enabled``.
    from sqlalchemy import select

    from app.models.orm import User

    user_row = (await ctx.session.execute(
        select(User).where(User.id == ctx.actor_id)
    )).scalar_one_or_none()
    learning_enabled = bool(getattr(user_row, "learning_enabled", True)) if user_row else True

    profile = await ArchitectProfileRepository.get_for_user(
        ctx.session, user_id=ctx.actor_id,
    )
    if profile is None:
        return ArchitectFingerprintOutput(
            user_id=ctx.actor_id,
            learning_enabled=learning_enabled,
            profile_exists=False,
        )

    return ArchitectFingerprintOutput(
        user_id=ctx.actor_id,
        learning_enabled=learning_enabled,
        profile_exists=True,
        project_count=int(profile.project_count or 0),
        preferred_themes=list(profile.preferred_themes or []),
        preferred_materials=list(profile.preferred_materials or []),
        preferred_palette_hexes=list(profile.preferred_palette_hexes or []),
        typical_room_dimensions_m=dict(profile.typical_room_dimensions_m or {}),
        tool_usage=list(profile.tool_usage or []),
        last_project_at=profile.last_project_at,
        last_extracted_at=profile.last_extracted_at,
    )


# ─────────────────────────────────────────────────────────────────────
# 2. get_client_profile
# ─────────────────────────────────────────────────────────────────────


class GetClientProfileInput(BaseModel):
    client_id: str = Field(
        description=(
            "Id of the client to look up. Must belong to the calling "
            "architect (cross-owner reads return 'not found')."
        ),
        min_length=1,
        max_length=120,
    )


class ClientProfileOutput(BaseModel):
    client_id: str
    name: str
    contact_email: str = ""
    profile_exists: bool
    project_count: int = 0
    typical_budget_inr: dict[str, Any] = Field(default_factory=dict)
    recurring_room_types: list[dict[str, Any]] = Field(default_factory=list)
    recurring_themes: list[dict[str, Any]] = Field(default_factory=list)
    accessibility_flags: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    last_project_at: Optional[str] = None
    last_extracted_at: Optional[str] = None


@tool(
    name="get_client_profile",
    description=(
        "Return the recurring-constraint profile for one of the "
        "architect's clients — typical budget band, recurring room "
        "types, themes, accessibility flags, free-form constraints. "
        "Owner-guarded: cross-architect reads return 'not found'. "
        "Use at the start of a new project for an existing client to "
        "anchor reasonable defaults. Read-only."
    ),
    timeout_seconds=15.0,
)
async def get_client_profile(
    ctx: ToolContext,
    input: GetClientProfileInput,
) -> ClientProfileOutput:
    if not ctx.actor_id:
        raise ToolError(
            "No actor_id on the agent context. The client-profile "
            "tool requires an authenticated user."
        )

    client = await ClientRepository.get_for_owner(
        ctx.session,
        client_id=input.client_id,
        owner_id=ctx.actor_id,
    )
    if client is None:
        raise ToolError(
            f"Client {input.client_id!r} not found for this architect."
        )

    profile = await ClientProfileRepository.get_for_client(
        ctx.session, client_id=input.client_id,
    )
    if profile is None:
        return ClientProfileOutput(
            client_id=input.client_id,
            name=client.name,
            contact_email=client.contact_email or "",
            profile_exists=False,
        )

    return ClientProfileOutput(
        client_id=input.client_id,
        name=client.name,
        contact_email=client.contact_email or "",
        profile_exists=True,
        project_count=int(profile.project_count or 0),
        typical_budget_inr=dict(profile.typical_budget_inr or {}),
        recurring_room_types=list(profile.recurring_room_types or []),
        recurring_themes=list(profile.recurring_themes or []),
        accessibility_flags=list(profile.accessibility_flags or []),
        constraints=list(profile.constraints or []),
        last_project_at=profile.last_project_at,
        last_extracted_at=profile.last_extracted_at,
    )


# ─────────────────────────────────────────────────────────────────────
# 3. resume_project_context
# ─────────────────────────────────────────────────────────────────────


class ResumeProjectContextInput(BaseModel):
    decision_limit: int = Field(
        default=10,
        ge=1,
        le=50,
        description="How many recent decisions to surface. Default 10.",
    )
    version_limit: int = Field(
        default=5,
        ge=1,
        le=50,
        description="How many recent design versions to surface. Default 5.",
    )


class VersionStub(BaseModel):
    version: int
    version_id: str
    change_type: str
    change_summary: str = ""
    created_at: Optional[str] = None


class DecisionStub(BaseModel):
    id: str
    title: str
    category: str
    version: int
    summary: str
    created_at: Optional[str] = None


class ResumeProjectContextOutput(BaseModel):
    project_id: str
    project_name: str
    project_status: str
    latest_version: int
    client_id: Optional[str] = None
    client_name: Optional[str] = None
    decision_count: int
    recent_decisions: list[DecisionStub]
    recent_versions: list[VersionStub]
    project_memory_chunk_count: int


@tool(
    name="resume_project_context",
    description=(
        "Composite briefing for the current project — the call to make "
        "at session start (or when resuming an old chat). Returns: "
        "project metadata, latest version, recent decisions (newest "
        "first), recent design-graph versions, client name (if "
        "linked), and project-memory chunk count. Use the result to "
        "ground the rest of the conversation without re-reading every "
        "tool's history. Read-only."
    ),
    timeout_seconds=20.0,
)
async def resume_project_context(
    ctx: ToolContext,
    input: ResumeProjectContextInput,
) -> ResumeProjectContextOutput:
    if not ctx.project_id:
        raise ToolError(
            "No project_id on the agent context. resume_project_context "
            "requires a project scope."
        )

    from sqlalchemy import select

    from app.models.orm import Client, DesignGraphVersion, Project

    project = (await ctx.session.execute(
        select(Project).where(Project.id == ctx.project_id)
    )).scalar_one_or_none()
    if project is None:
        raise ToolError(f"Project {ctx.project_id!r} not found.")

    # Owner check — defence in depth.
    if ctx.actor_id and project.owner_id and project.owner_id != ctx.actor_id:
        raise ToolError(f"Project {ctx.project_id!r} not found.")

    client_name: Optional[str] = None
    if project.client_id:
        client_row = (await ctx.session.execute(
            select(Client).where(Client.id == project.client_id)
        )).scalar_one_or_none()
        if client_row is not None:
            client_name = client_row.name

    # Recent versions (newest first).
    version_rows = (await ctx.session.execute(
        select(DesignGraphVersion)
        .where(DesignGraphVersion.project_id == ctx.project_id)
        .order_by(DesignGraphVersion.version.desc())
        .limit(input.version_limit)
    )).scalars().all()

    versions = [
        VersionStub(
            version=int(v.version or 0),
            version_id=str(v.id),
            change_type=str(v.change_type or ""),
            change_summary=str(v.change_summary or ""),
            created_at=v.created_at.isoformat()
                if hasattr(v.created_at, "isoformat") else None,
        )
        for v in version_rows
    ]

    # Recent decisions (newest first).
    decision_rows = await DesignDecisionRepository.list_for_project(
        ctx.session,
        project_id=ctx.project_id,
        limit=input.decision_limit,
    )
    decisions = [
        DecisionStub(
            id=str(d.id),
            title=str(d.title or ""),
            category=str(d.category or "general"),
            version=int(d.version or 0),
            summary=str(d.summary or ""),
            created_at=d.created_at.isoformat()
                if hasattr(d.created_at, "isoformat") else None,
        )
        for d in decision_rows
    ]
    decision_count = await DesignDecisionRepository.count_for_project(
        ctx.session, project_id=ctx.project_id,
    )

    chunk_count = await ProjectMemoryRepository.count_for_project(
        ctx.session, project_id=ctx.project_id,
    )

    return ResumeProjectContextOutput(
        project_id=ctx.project_id,
        project_name=str(project.name or ""),
        project_status=str(project.status or "draft"),
        latest_version=int(project.latest_version or 0),
        client_id=project.client_id,
        client_name=client_name,
        decision_count=decision_count,
        recent_decisions=decisions,
        recent_versions=versions,
        project_memory_chunk_count=chunk_count,
    )
