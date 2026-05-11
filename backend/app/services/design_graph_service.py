"""Design Graph Service — persistence, versioning, and retrieval."""

import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import DesignGraphVersion, GeneratedAsset, Project

logger = logging.getLogger(__name__)


async def create_project(
    db: AsyncSession,
    owner_id: str,
    name: str,
    description: str = "",
    *,
    project_type: str = "residential",
    project_sub_type: str = "",
    project_scale: str = "",
) -> Project:
    project = Project(
        owner_id=owner_id,
        name=name,
        description=description,
        project_type=project_type,
        project_sub_type=project_sub_type or None,
        project_scale=project_scale or None,
        status="draft",
        latest_version=0,
    )
    db.add(project)
    await db.flush()
    return project


async def save_graph_version(
    db: AsyncSession,
    project_id: str,
    graph_data: dict,
    change_type: str = "initial",
    change_summary: str = "",
    changed_object_ids: list[str] | None = None,
    parent_version_id: str | None = None,
    prompt: str | None = None,
) -> DesignGraphVersion:
    """Persist a new design graph version and bump the project counter.

    The optional ``prompt`` is the originating user text — captured on
    initial generation and propagated through edits and theme switches
    so any version can be re-rendered with full context. Pre-migration-
    0028 rows have NULL prompts; the pipeline tolerates that.
    """

    # Determine version number
    result = await db.execute(
        select(func.coalesce(func.max(DesignGraphVersion.version), 0)).where(
            DesignGraphVersion.project_id == project_id
        )
    )
    current_max = result.scalar_one()
    new_version = current_max + 1

    version = DesignGraphVersion(
        project_id=project_id,
        version=new_version,
        parent_version_id=parent_version_id,
        change_type=change_type,
        change_summary=change_summary,
        changed_object_ids=changed_object_ids or [],
        graph_data=graph_data,
        prompt=prompt,
    )
    db.add(version)

    # Update project
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one()
    project.latest_version = new_version
    project.status = "ready"

    await db.flush()
    logger.info("Saved version %d for project %s", new_version, project_id)
    return version


async def save_render_asset(
    db: AsyncSession,
    *,
    graph_version_id: str,
    storage_key: str,
    mime_type: str = "image/png",
    metadata: dict | None = None,
) -> GeneratedAsset:
    """Persist a 2D render as a GeneratedAsset linked to a graph version.

    The ``storage_key`` is whatever the image provider returned — today
    a base64 data URI from Gemini. Field name is generic so a later
    migration to a CDN/S3 reference is a value-shape change, not a
    schema change. Always best-effort: callers should treat this as
    advisory and never fail the surrounding op if asset persistence
    raises (the graph is already saved at that point).
    """
    asset = GeneratedAsset(
        graph_version_id=graph_version_id,
        asset_type="render_2d",
        storage_key=storage_key,
        mime_type=mime_type,
        metadata_=metadata or {},
    )
    db.add(asset)
    await db.flush()
    return asset


async def get_latest_version(
    db: AsyncSession,
    project_id: str,
) -> DesignGraphVersion | None:
    result = await db.execute(
        select(DesignGraphVersion)
        .where(DesignGraphVersion.project_id == project_id)
        .order_by(DesignGraphVersion.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_latest_render_for_version(
    db: AsyncSession,
    graph_version_id: str,
) -> GeneratedAsset | None:
    """Most recent ``render_2d`` asset for a graph version, if any.

    A version can carry multiple render assets over time (an admin
    re-render, a future "regenerate without changing graph" affordance).
    The newest one wins — that's what the gallery should display when
    re-opening a project.
    """
    result = await db.execute(
        select(GeneratedAsset)
        .where(
            GeneratedAsset.graph_version_id == graph_version_id,
            GeneratedAsset.asset_type == "render_2d",
        )
        .order_by(GeneratedAsset.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_version(
    db: AsyncSession,
    project_id: str,
    version: int,
) -> DesignGraphVersion | None:
    result = await db.execute(
        select(DesignGraphVersion).where(
            DesignGraphVersion.project_id == project_id,
            DesignGraphVersion.version == version,
        )
    )
    return result.scalar_one_or_none()


async def list_versions(
    db: AsyncSession,
    project_id: str,
) -> list[DesignGraphVersion]:
    result = await db.execute(
        select(DesignGraphVersion)
        .where(DesignGraphVersion.project_id == project_id)
        .order_by(DesignGraphVersion.version.desc())
    )
    return list(result.scalars().all())


async def get_project(
    db: AsyncSession,
    project_id: str,
) -> Project | None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


async def list_projects(
    db: AsyncSession,
    owner_id: str,
    offset: int = 0,
    limit: int = 50,
) -> tuple[list[Project], int]:
    count_result = await db.execute(
        select(func.count(Project.id)).where(Project.owner_id == owner_id)
    )
    total = count_result.scalar_one()

    result = await db.execute(
        select(Project)
        .where(Project.owner_id == owner_id)
        .order_by(Project.updated_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all()), total
