"""Database-backed estimate history queries."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import DesignGraphVersion, EstimateSnapshot


async def fetch_project_estimate_history(db: AsyncSession, project_id: str) -> list[dict]:
    stmt = (
        select(EstimateSnapshot.created_at, EstimateSnapshot.total_high)
        .join(DesignGraphVersion, EstimateSnapshot.graph_version_id == DesignGraphVersion.id)
        .where(DesignGraphVersion.project_id == project_id)
        .order_by(EstimateSnapshot.created_at.asc())
    )
    rows = (await db.execute(stmt)).all()
    return [
        {
            "timestamp": created_at.isoformat(),
            "total": float(total_high or 0.0),
        }
        for created_at, total_high in rows
    ]
