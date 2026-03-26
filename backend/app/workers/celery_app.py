"""Celery application — broker config and task autodiscovery."""

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "katha_workers",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.tasks.generate_design_task": {"queue": "generation"},
        "app.workers.tasks.compute_estimate_task": {"queue": "estimation"},
        "app.workers.tasks.render_2d_task": {"queue": "rendering"},
        "app.workers.tasks.build_3d_scene_task": {"queue": "rendering"},
        "app.workers.tasks.ingest_document_task": {"queue": "ingestion"},
    },
)

celery_app.autodiscover_tasks(["app.workers"])
