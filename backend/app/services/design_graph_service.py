"""Design Graph Service — persistence, versioning, and retrieval."""

import logging

from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import (
    DesignGraphVersion,
    EstimateLineItem,
    EstimateSnapshot,
    GeneratedAsset,
    Project,
)
from app.services.graph_normalizer import normalize_graph
from app.services.storage import read_bytes

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
    region: str = "india",
) -> Project:
    from app.services.regions import normalize_region

    project = Project(
        owner_id=owner_id,
        name=name,
        description=description,
        project_type=project_type,
        project_sub_type=project_sub_type or None,
        project_scale=project_scale or None,
        region=normalize_region(region),
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

    # Single chokepoint: every graph — initial generation, prompt edit,
    # manual edit, theme switch — is normalized + validated here before it
    # is persisted. Downstream renderers / 3D / cost read graph_data and can
    # rely on the canonical axis + unit + bounds contract. Idempotent, so
    # re-saving an already-clean graph is a no-op (modulo the report).
    normalized_graph, report = normalize_graph(graph_data)
    if report.get("corrections"):
        logger.info(
            "Normalized graph for project %s v%d: %d correction(s), ok=%s",
            project_id,
            new_version,
            len(report["corrections"]),
            report.get("ok"),
        )
    if not report.get("ok") and report.get("errors"):
        logger.warning(
            "Graph for project %s v%d failed validation after normalization: %s",
            project_id,
            new_version,
            report["errors"],
        )

    version = DesignGraphVersion(
        project_id=project_id,
        version=new_version,
        parent_version_id=parent_version_id,
        change_type=change_type,
        change_summary=change_summary,
        changed_object_ids=changed_object_ids or [],
        graph_data=normalized_graph,
        raw_graph_data=graph_data,
        normalization_report=report,
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


async def set_version_bboxes(
    db: AsyncSession,
    version_id: str,
    bboxes: list[dict],
) -> None:
    """Persist vision-grounded hotspots on a version so re-opening a project
    reuses them instead of recomputing (or re-detecting). Best-effort — never
    raises; the request-level commit flushes it."""
    if not version_id or not bboxes:
        return
    try:
        await db.execute(
            update(DesignGraphVersion)
            .where(DesignGraphVersion.id == version_id)
            .values(objects_bbox=bboxes)
        )
        await db.flush()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Persisting objects_bbox failed for version %s: %s", version_id, exc)


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


async def get_version_by_id(
    db: AsyncSession,
    version_id: str,
) -> DesignGraphVersion | None:
    result = await db.execute(
        select(DesignGraphVersion).where(DesignGraphVersion.id == version_id)
    )
    return result.scalar_one_or_none()


async def load_render_bytes(
    db: AsyncSession,
    graph_version_id: str,
) -> bytes | None:
    """Raw bytes of a version's newest finished render, or None. Used by the
    localized edit render to composite the changed object over the prior image."""
    asset = await get_latest_render_for_version(db, graph_version_id)
    if asset is None or not asset.storage_key:
        return None
    key = asset.storage_key
    if key.startswith("data:"):
        import base64
        try:
            return base64.b64decode(key.split(",", 1)[1])
        except Exception:  # noqa: BLE001
            return None
    try:
        return await read_bytes(key)
    except Exception:  # noqa: BLE001 — best-effort; caller falls back to a full render
        logger.warning("could not load render bytes for version %s", graph_version_id)
        return None


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


class VersionDeleteError(Exception):
    """Raised when a version can't be deleted (missing, or the last one)."""


async def delete_version(
    db: AsyncSession,
    project_id: str,
    version: int,
) -> dict:
    """Delete a single design version and everything that hangs off it, then
    re-point the project's ``latest_version`` at the newest survivor.

    The FKs into ``design_graph_versions`` carry no ON DELETE CASCADE, so the
    dependent rows are cleared first, in order: any child version's
    ``parent_version_id`` link is nulled, then the version's estimate line
    items → snapshots, then its render assets, then the version row itself.
    Refuses to delete a project's only remaining version — a project must
    always keep at least one. All within the caller's transaction, so a raised
    error rolls the whole thing back.

    Returns ``{"latest_version": int, "remaining": [int, ...]}``.
    """
    target = await get_version(db, project_id, version)
    if target is None:
        raise VersionDeleteError(f"version {version} not found")

    existing = await list_versions(db, project_id)  # newest-first
    if len(existing) <= 1:
        raise VersionDeleteError("cannot delete the project's only version")

    vid = target.id

    # 1. Drop self-referential parent links pointing at the target.
    await db.execute(
        update(DesignGraphVersion)
        .where(DesignGraphVersion.parent_version_id == vid)
        .values(parent_version_id=None)
    )
    # 2. Estimate line items -> snapshots for this version.
    snap_ids = (
        await db.execute(
            select(EstimateSnapshot.id).where(
                EstimateSnapshot.graph_version_id == vid
            )
        )
    ).scalars().all()
    if snap_ids:
        await db.execute(
            delete(EstimateLineItem).where(EstimateLineItem.snapshot_id.in_(snap_ids))
        )
        await db.execute(
            delete(EstimateSnapshot).where(EstimateSnapshot.id.in_(snap_ids))
        )
    # 3. Render assets for this version.
    await db.execute(
        delete(GeneratedAsset).where(GeneratedAsset.graph_version_id == vid)
    )
    # 4. The version row itself.
    await db.execute(
        delete(DesignGraphVersion).where(DesignGraphVersion.id == vid)
    )

    # 5. Re-point latest_version at the newest survivor.
    remaining = sorted(v.version for v in existing if v.version != version)
    new_latest = remaining[-1] if remaining else 0
    project = await get_project(db, project_id)
    if project is not None:
        project.latest_version = new_latest

    await db.flush()
    logger.info(
        "Deleted version %d for project %s (latest now %d)",
        version, project_id, new_latest,
    )
    return {"latest_version": new_latest, "remaining": remaining}


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
