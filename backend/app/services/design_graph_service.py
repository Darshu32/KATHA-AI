"""Design Graph Service — persistence, versioning, and retrieval."""

import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import DesignGraphVersion, Project

logger = logging.getLogger(__name__)


async def create_project(
    db: AsyncSession,
    owner_id: str,
    name: str,
    description: str = "",
) -> Project:
    project = Project(
        owner_id=owner_id,
        name=name,
        description=description,
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
) -> DesignGraphVersion:
    """Persist a new design graph version and bump the project counter."""

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
