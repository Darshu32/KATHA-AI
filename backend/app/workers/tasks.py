"""Celery tasks for long-running background jobs."""

import asyncio
import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Helper to run async code inside a sync Celery task."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(bind=True, name="app.workers.tasks.generate_design_task")
def generate_design_task(self, project_id: str, prompt: str, room_type: str, style: str):
    """Background task: full design generation pipeline."""
    from app.database import async_session_factory
    from app.services.generation_pipeline import run_initial_generation

    logger.info("Task %s: generating design for project %s", self.request.id, project_id)

    async def _run():
        async with async_session_factory() as db:
            try:
                result = await run_initial_generation(
                    db=db,
                    project_id=project_id,
                    prompt=prompt,
                    room_type=room_type,
                    style=style,
                )
                await db.commit()
                return result
            except Exception:
                await db.rollback()
                raise

    return _run_async(_run())


@celery_app.task(bind=True, name="app.workers.tasks.run_design_pipeline_task")
def run_design_pipeline_task(self, design_id: str, start_stage: str | None = None):
    """Background task: run the design-intake orchestrator for a stored design."""
    from app.services.ai_orchestrator import run_pipeline

    logger.info(
        "Task %s: running design pipeline for design %s from stage %s",
        self.request.id,
        design_id,
        start_stage or "theme",
    )
    return _run_async(run_pipeline(design_id, start_stage=start_stage))


@celery_app.task(bind=True, name="app.workers.tasks.compute_estimate_task")
def compute_estimate_task(self, graph_data: dict):
    """Background task: compute material/cost estimate from a design graph."""
    from app.services.estimation_engine import compute_estimate

    logger.info("Task %s: computing estimate", self.request.id)
    return compute_estimate(graph_data)


@celery_app.task(bind=True, name="app.workers.tasks.render_2d_task")
def render_2d_task(self, project_id: str, version_id: str, render_prompt: str):
    """Background task: generate 2D render from the design graph render prompt.

    In production this would call an image generation API (DALL-E, Stable Diffusion, etc.)
    and upload the result to object storage.
    """
    logger.info("Task %s: 2D render for project %s version %s", self.request.id, project_id, version_id)

    # TODO: integrate image generation API
    # 1. Call image API with render_prompt
    # 2. Upload result to S3/R2
    # 3. Store GeneratedAsset record

    return {
        "project_id": project_id,
        "version_id": version_id,
        "asset_type": "render_2d",
        "status": "placeholder",
        "message": "Image generation API integration pending",
    }


@celery_app.task(bind=True, name="app.workers.tasks.build_3d_scene_task")
def build_3d_scene_task(self, project_id: str, version_id: str, graph_data: dict):
    """Background task: build 3D scene data from the design graph.

    This converts the design graph objects into Three.js-compatible scene JSON
    that the frontend 3D viewer can load directly.
    """
    logger.info("Task %s: 3D scene build for project %s", self.request.id, project_id)

    scene_objects = []
    for obj in graph_data.get("objects", []):
        dims = obj.get("dimensions", {})
        pos = obj.get("position", {})
        rot = obj.get("rotation", {})

        scene_objects.append({
            "id": obj.get("id", ""),
            "type": obj.get("type", "box"),
            "name": obj.get("name", ""),
            "geometry": {
                "type": _map_to_geometry_type(obj.get("type", "")),
                "args": [
                    dims.get("width", 1),
                    dims.get("height", 1),
                    dims.get("length", 1),
                ],
            },
            "position": [pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)],
            "rotation": [rot.get("x", 0), rot.get("y", 0), rot.get("z", 0)],
            "material": {
                "color": obj.get("color", "#cccccc"),
                "type": "standard",
            },
        })

    # Build lighting
    scene_lights = []
    for light in graph_data.get("lighting", []):
        pos = light.get("position", {})
        scene_lights.append({
            "id": light.get("id", ""),
            "type": light.get("type", "point"),
            "position": [pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)],
            "intensity": light.get("intensity", 1),
            "color": light.get("color", "#ffffff"),
        })

    return {
        "project_id": project_id,
        "version_id": version_id,
        "scene": {
            "objects": scene_objects,
            "lights": scene_lights,
        },
        "status": "built",
    }


@celery_app.task(bind=True, name="app.workers.tasks.ingest_document_task")
def ingest_document_task(self, document_id: str, storage_key: str):
    """Background task: parse and embed a knowledge document.

    1. Download document from storage
    2. Parse text (PDF, images, tables)
    3. Chunk by topic
    4. Generate embeddings
    5. Store in pgvector
    """
    logger.info("Task %s: ingesting document %s", self.request.id, document_id)

    # TODO: implement document parsing pipeline
    return {
        "document_id": document_id,
        "status": "placeholder",
        "message": "Document ingestion pipeline pending",
    }


@celery_app.task(bind=True, name="app.workers.tasks.refresh_architecture_task")
def refresh_architecture_task(self, force: bool = False):
    """Background task: refresh the architecture graph snapshot."""
    from app.database import async_session_factory
    from app.services.architecture_query_service import refresh_architecture

    logger.info("Task %s: refreshing architecture graph", self.request.id)

    async def _run():
        async with async_session_factory() as db:
            try:
                result = await refresh_architecture(db, force=force)
                await db.commit()
                return result
            except Exception:
                await db.rollback()
                raise

    return _run_async(_run())


def _map_to_geometry_type(obj_type: str) -> str:
    """Map design object types to Three.js geometry types."""
    mapping = {
        "wall": "box",
        "door": "box",
        "window": "box",
        "sofa": "box",
        "table": "box",
        "chair": "box",
        "bed": "box",
        "desk": "box",
        "shelf": "box",
        "cabinet": "box",
        "rug": "plane",
        "light_fixture": "sphere",
        "lamp": "cylinder",
        "plant": "sphere",
        "pillow": "sphere",
    }
    return mapping.get(obj_type.lower(), "box")
