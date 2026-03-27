"""Architecture knowledge routes."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.middleware import get_current_user
from app.models.orm import User
from app.services.architecture_query_service import (
    ask_architecture,
    get_architecture_quality,
    get_architecture_status,
    get_architecture_summary,
    get_dependency_analysis,
    get_feature_flow,
    index_architecture,
)

router = APIRouter(prefix="/architecture", tags=["architecture"])


class ArchitectureQuestionRequest(BaseModel):
    question: str


class ArchitectureRefreshRequest(BaseModel):
    force: bool = False


@router.post("/index")
async def index_architecture_route(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    return await index_architecture(db)


@router.post("/refresh")
async def architecture_refresh_route(
    payload: ArchitectureRefreshRequest,
    user: User = Depends(get_current_user),
):
    _ = user
    try:
        from app.workers.tasks import refresh_architecture_task

        task = refresh_architecture_task.delay(payload.force)
        return {
            "status": "queued",
            "task_id": task.id,
            "mode": "background",
        }
    except Exception:
        from app.database import async_session_factory
        from app.services.architecture_query_service import refresh_architecture

        async with async_session_factory() as db:
            result = await refresh_architecture(db, force=payload.force)
            await db.commit()
            return {
                "status": "completed",
                "mode": "inline",
                **result,
            }


@router.get("/summary")
async def architecture_summary_route(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    return await get_architecture_summary(db)


@router.get("/status")
async def architecture_status_route(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    return await get_architecture_status(db)


@router.get("/quality")
async def architecture_quality_route(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    return await get_architecture_quality(db)


@router.get("/feature-flow/{feature_name}")
async def architecture_feature_flow_route(
    feature_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    return await get_feature_flow(db, feature_name)


@router.get("/dependencies")
async def architecture_dependencies_route(
    query: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    return await get_dependency_analysis(db, query)


@router.post("/ask")
async def architecture_ask_route(
    payload: ArchitectureQuestionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _ = user
    return await ask_architecture(db, payload.question)
