"""Data layer primitives — schema conventions, repositories, caching, audit.

This package establishes the contract for *every* table that holds business
data in KATHA-AI. The conventions enforced here are what make Stages 1–3
(externalize hardcoded data) safe and reproducible:

- Versioning      → no destructive updates; history is immutable
- Soft delete     → records can be removed without losing audit trail
- Effective dates → time-bounded validity for prices, codes, themes, etc.
- Source tags     → every row knows where it came from (admin, scraper, seed)
- Audit log       → who changed what, when, why

Stage 0 ships the substrate. Stage 1 will be the first real consumer
(pricing engine).
"""

from app.db.audit import AuditEvent, AuditLog
from app.db.cache import async_cached, invalidate
from app.db.conventions import (
    ActorMixin,
    EffectiveDatesMixin,
    SoftDeleteMixin,
    SourceMixin,
    TimestampMixin,
    UUIDMixin,
    VersionedMixin,
)
from app.db.repository import BaseRepository

__all__ = [
    "ActorMixin",
    "AuditEvent",
    "AuditLog",
    "BaseRepository",
    "EffectiveDatesMixin",
    "SoftDeleteMixin",
    "SourceMixin",
    "TimestampMixin",
    "UUIDMixin",
    "VersionedMixin",
    "async_cached",
    "invalidate",
]
