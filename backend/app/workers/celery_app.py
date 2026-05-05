"""Celery application — broker config, task routing, beat schedule."""

from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "katha_workers",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Explicit task module list — autodiscover_tasks only finds the
    # canonical "tasks.py", which would silently exclude feed_tasks,
    # memory_tasks, and memory_extraction. Without this, beat would
    # fire scheduled jobs that no worker has registered.
    include=[
        "app.workers.tasks",
        "app.workers.feed_tasks",
        "app.workers.memory_tasks",
        "app.workers.memory_extraction",
    ],
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
        "app.workers.tasks.run_design_pipeline_task": {"queue": "generation"},
        "app.workers.tasks.compute_estimate_task": {"queue": "estimation"},
        "app.workers.tasks.render_2d_task": {"queue": "rendering"},
        "app.workers.tasks.build_3d_scene_task": {"queue": "rendering"},
        "app.workers.tasks.ingest_document_task": {"queue": "ingestion"},
        "app.workers.tasks.refresh_architecture_task": {"queue": "ingestion"},
        # Stage 5D — project memory indexing.
        "app.workers.memory_tasks.index_design_version_task": {"queue": "ingestion"},
        # Stage 8 — architect / client profile extraction.
        "app.workers.memory_extraction.extract_architect_fingerprint_task": {
            "queue": "ingestion",
        },
        "app.workers.memory_extraction.extract_client_profile_task": {
            "queue": "ingestion",
        },
        # Stage 12 — live data feed refreshes (own queue so a sluggish
        # vendor scraper never starves the design / estimation queues).
        "app.workers.feed_tasks.refresh_mcx_task": {"queue": "feeds"},
        "app.workers.feed_tasks.refresh_fx_task": {"queue": "feeds"},
        "app.workers.feed_tasks.refresh_gst_task": {"queue": "feeds"},
        "app.workers.feed_tasks.refresh_vendor_jaquar_task": {"queue": "feeds"},
        "app.workers.feed_tasks.refresh_vendor_kohler_task": {"queue": "feeds"},
        "app.workers.feed_tasks.refresh_vendor_asian_paints_task": {
            "queue": "feeds",
        },
    },
    # Stage 12 — beat schedule. Cadences match upstream change
    # frequency: commodities + FX move daily, GST barely moves,
    # vendor catalogs settle on a multi-day cycle. Tweak in a hotfix
    # without redeploying the worker by editing this map.
    beat_schedule={
        "feed-mcx-refresh": {
            "task": "app.workers.feed_tasks.refresh_mcx_task",
            "schedule": crontab(minute=0, hour="*/6"),
        },
        "feed-fx-refresh": {
            "task": "app.workers.feed_tasks.refresh_fx_task",
            "schedule": crontab(minute=15, hour="*/6"),
        },
        "feed-gst-refresh": {
            "task": "app.workers.feed_tasks.refresh_gst_task",
            "schedule": crontab(minute=30, hour=2, day_of_week=1),
        },
        "feed-vendor-jaquar-refresh": {
            "task": "app.workers.feed_tasks.refresh_vendor_jaquar_task",
            "schedule": crontab(minute=0, hour=3),
        },
        "feed-vendor-kohler-refresh": {
            "task": "app.workers.feed_tasks.refresh_vendor_kohler_task",
            "schedule": crontab(minute=20, hour=3),
        },
        "feed-vendor-asian-paints-refresh": {
            "task": "app.workers.feed_tasks.refresh_vendor_asian_paints_task",
            "schedule": crontab(minute=40, hour=3),
        },
    },
)

celery_app.autodiscover_tasks(["app.workers"])
