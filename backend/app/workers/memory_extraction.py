"""Stage 8 — Celery tasks for nightly memory extraction.

Two tasks, both privacy-gated:

- :func:`extract_architect_fingerprint_task` — refreshes the
  ``architect_profiles`` row for a single user. Refuses to run when
  ``User.learning_enabled`` is False (privacy contract).
- :func:`extract_client_profile_task` — refreshes the
  ``client_profiles`` row for a single client. Same privacy gate
  via the client's ``primary_user_id``.

Why per-user / per-client tasks
-------------------------------
Easier to schedule incrementally — Celery beat fires one task per
architect per night, parallelism is bounded by the worker pool.
A single "extract everyone" task would not scale + can't honour
per-user opt-outs cheanly.

Privacy contract
----------------
- The User's ``learning_enabled`` flag is read **at the start of
  every task run**. Disabling at any point means the next nightly
  run becomes a no-op for that user — no race with mid-flight
  extraction.
- The existing profile row is **not** deleted when learning is
  disabled. It just stops refreshing. The architect can wipe it
  via the future settings UI.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from app.workers.celery_app import celery_app

log = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine inside a sync Celery task body."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ─────────────────────────────────────────────────────────────────────
# extract_architect_fingerprint_task
# ─────────────────────────────────────────────────────────────────────


async def _extract_architect_async(user_id: str) -> dict:
    """Implementation of the architect-fingerprint task.

    Pulls the user's design graphs + recent tool-call audit events,
    runs the deterministic extractor, upserts the profile row.
    """
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.db.audit import AuditEvent
    from app.models.orm import (
        ArchitectProfile,  # noqa: F401 — ensures registered
        DesignGraphVersion,
        Project,
        User,
    )
    from app.profiles import extract_architect_fingerprint
    from app.repositories.architects import ArchitectProfileRepository

    async with async_session_factory() as db:
        try:
            # 1. Privacy gate.
            user = (await db.execute(
                select(User).where(User.id == user_id)
            )).scalar_one_or_none()
            if user is None:
                return {
                    "ok": False,
                    "skipped_reason": "user_not_found",
                    "user_id": user_id,
                }
            if not bool(getattr(user, "learning_enabled", True)):
                log.info(
                    "extract_architect_fingerprint skipped — "
                    "learning_enabled=false for user=%s",
                    user_id,
                )
                return {
                    "ok": True,
                    "skipped_reason": "learning_disabled",
                    "user_id": user_id,
                }

            # 2. Pull the user's project ids.
            project_ids = [
                p.id for p in (await db.execute(
                    select(Project).where(Project.owner_id == user_id)
                )).scalars().all()
            ]

            # 3. For each project, fetch the latest design-graph version.
            design_graphs: list[dict] = []
            last_project_at: Optional[str] = None
            for pid in project_ids:
                latest = (await db.execute(
                    select(DesignGraphVersion)
                    .where(DesignGraphVersion.project_id == pid)
                    .order_by(DesignGraphVersion.version.desc())
                    .limit(1)
                )).scalar_one_or_none()
                if latest is None:
                    continue
                design_graphs.append(latest.graph_data or {})
                if hasattr(latest, "created_at") and latest.created_at:
                    iso = latest.created_at.isoformat()
                    if last_project_at is None or iso > last_project_at:
                        last_project_at = iso

            # 4. Pull tool-call audit events for the user.
            audit_rows = (await db.execute(
                select(AuditEvent)
                .where(
                    AuditEvent.actor_id == user_id,
                    AuditEvent.action == "tool_call",
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(2000)
            )).scalars().all()
            tool_calls = [
                {"action": "tool_call", "after": dict(r.after or {})}
                for r in audit_rows
            ]

            # 5. Run the deterministic extractor.
            fingerprint = extract_architect_fingerprint(
                user_id=user_id,
                design_graphs=design_graphs,
                tool_calls=tool_calls,
                last_project_at=last_project_at,
            )

            # 6. Upsert the profile row.
            await ArchitectProfileRepository.upsert(
                db,
                user_id=fingerprint.user_id,
                project_count=fingerprint.project_count,
                preferred_themes=fingerprint.preferred_themes,
                preferred_materials=fingerprint.preferred_materials,
                preferred_palette_hexes=fingerprint.preferred_palette_hexes,
                typical_room_dimensions_m=fingerprint.typical_room_dimensions_m,
                tool_usage=fingerprint.tool_usage,
                last_project_at=fingerprint.last_project_at,
            )
            await db.commit()
            return {
                "ok": True,
                "user_id": user_id,
                "project_count": fingerprint.project_count,
                "tool_call_samples": len(tool_calls),
            }
        except Exception:
            await db.rollback()
            raise


@celery_app.task(
    bind=True,
    name="app.workers.memory_extraction.extract_architect_fingerprint_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def extract_architect_fingerprint_task(self, *, user_id: str) -> dict:
    """Refresh one architect's fingerprint. Privacy-gated."""
    log.info(
        "extract_architect_fingerprint_task start user=%s task=%s",
        user_id, self.request.id,
    )
    return _run_async(_extract_architect_async(user_id))


# ─────────────────────────────────────────────────────────────────────
# extract_client_profile_task
# ─────────────────────────────────────────────────────────────────────


async def _extract_client_async(client_id: str) -> dict:
    """Implementation of the client-profile task."""
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.models.orm import (
        Client,
        DesignDecision,
        DesignGraphVersion,
        EstimateSnapshot,
        Project,
        User,
    )
    from app.profiles import extract_client_pattern
    from app.repositories.clients import ClientProfileRepository

    async with async_session_factory() as db:
        try:
            # 1. Resolve client + the architect who owns it.
            client = (await db.execute(
                select(Client).where(Client.id == client_id)
            )).scalar_one_or_none()
            if client is None:
                return {
                    "ok": False,
                    "skipped_reason": "client_not_found",
                    "client_id": client_id,
                }
            primary_user_id = client.primary_user_id

            # 2. Privacy gate via the architect.
            user = (await db.execute(
                select(User).where(User.id == primary_user_id)
            )).scalar_one_or_none()
            if user is None or not bool(getattr(user, "learning_enabled", True)):
                log.info(
                    "extract_client_profile skipped — "
                    "primary architect's learning is disabled "
                    "(client=%s user=%s)",
                    client_id, primary_user_id,
                )
                return {
                    "ok": True,
                    "skipped_reason": "learning_disabled",
                    "client_id": client_id,
                }

            # 3. Pull the client's projects + a few attached fields.
            projects = (await db.execute(
                select(Project).where(Project.client_id == client_id)
            )).scalars().all()

            project_payloads: list[dict] = []
            last_project_at: Optional[str] = None
            for project in projects:
                # Latest version's graph_data.
                latest_version = (await db.execute(
                    select(DesignGraphVersion)
                    .where(DesignGraphVersion.project_id == project.id)
                    .order_by(DesignGraphVersion.version.desc())
                    .limit(1)
                )).scalar_one_or_none()
                graph_data = (
                    latest_version.graph_data
                    if latest_version is not None else {}
                )

                # Latest estimate.
                estimate_total = None
                if latest_version is not None:
                    snap = (await db.execute(
                        select(EstimateSnapshot)
                        .where(EstimateSnapshot.graph_version_id == latest_version.id)
                        .order_by(EstimateSnapshot.created_at.desc())
                        .limit(1)
                    )).scalar_one_or_none()
                    if snap is not None:
                        estimate_total = float(getattr(snap, "total_high", 0) or 0)

                # Decisions tagged accessibility.
                decision_rows = (await db.execute(
                    select(DesignDecision)
                    .where(DesignDecision.project_id == project.id)
                )).scalars().all()
                decisions = [
                    {"tags": list(d.tags or [])}
                    for d in decision_rows
                ]

                project_payloads.append({
                    "description": project.description or "",
                    "estimate_total_inr": estimate_total,
                    "graph_data": graph_data,
                    "decisions": decisions,
                })

                if hasattr(project, "updated_at") and project.updated_at:
                    iso = project.updated_at.isoformat()
                    if last_project_at is None or iso > last_project_at:
                        last_project_at = iso

            # 4. Run the deterministic extractor.
            pattern = extract_client_pattern(
                client_id=client_id,
                projects=project_payloads,
                last_project_at=last_project_at,
            )

            # 5. Upsert.
            await ClientProfileRepository.upsert(
                db,
                client_id=pattern.client_id,
                project_count=pattern.project_count,
                typical_budget_inr=pattern.typical_budget_inr,
                recurring_room_types=pattern.recurring_room_types,
                recurring_themes=pattern.recurring_themes,
                accessibility_flags=pattern.accessibility_flags,
                constraints=pattern.constraints,
                last_project_at=pattern.last_project_at,
            )
            await db.commit()
            return {
                "ok": True,
                "client_id": client_id,
                "project_count": pattern.project_count,
            }
        except Exception:
            await db.rollback()
            raise


@celery_app.task(
    bind=True,
    name="app.workers.memory_extraction.extract_client_profile_task",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    max_retries=3,
)
def extract_client_profile_task(self, *, client_id: str) -> dict:
    """Refresh one client's profile. Privacy-gated."""
    log.info(
        "extract_client_profile_task start client=%s task=%s",
        client_id, self.request.id,
    )
    return _run_async(_extract_client_async(client_id))


# ─────────────────────────────────────────────────────────────────────
# Dispatch helpers (sync, called from anywhere)
# ─────────────────────────────────────────────────────────────────────


def dispatch_architect_fingerprint(*, user_id: str) -> Optional[str]:
    """Send a fingerprint refresh to Celery. Returns the task id."""
    try:
        async_result = extract_architect_fingerprint_task.apply_async(
            kwargs={"user_id": user_id},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Failed to dispatch extract_architect_fingerprint_task "
            "user=%s: %s", user_id, exc,
        )
        return None
    return str(getattr(async_result, "id", "") or "") or None


def dispatch_client_profile(*, client_id: str) -> Optional[str]:
    try:
        async_result = extract_client_profile_task.apply_async(
            kwargs={"client_id": client_id},
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Failed to dispatch extract_client_profile_task "
            "client=%s: %s", client_id, exc,
        )
        return None
    return str(getattr(async_result, "id", "") or "") or None


__all__ = [
    "dispatch_architect_fingerprint",
    "dispatch_client_profile",
    "extract_architect_fingerprint_task",
    "extract_client_profile_task",
]
