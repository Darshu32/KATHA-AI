"""Storage factory — pick a backend based on settings.

We memoise the result so the same backend instance is reused across
the app's lifetime — the S3 client is heavy to construct and the
local backend opens its root directory once.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.config import get_settings
from app.storage.base import StorageBackend
from app.storage.local import LocalStorageBackend
from app.storage.s3 import S3StorageBackend

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cached: Optional[StorageBackend] = None


def get_storage_backend() -> StorageBackend:
    """Return the configured backend. Memoised — safe to call often."""
    global _cached
    with _lock:
        if _cached is not None:
            return _cached

        settings = get_settings()
        kind = (settings.storage_backend or "local").strip().lower()

        if kind == "s3":
            backend: StorageBackend = S3StorageBackend(
                bucket=settings.s3_bucket,
                endpoint_url=settings.s3_endpoint or "",
                access_key=settings.s3_access_key or "",
                secret_key=settings.s3_secret_key or "",
                region=settings.s3_region or "auto",
            )
        else:
            if kind != "local":
                log.warning(
                    "Unknown storage_backend %r — falling back to local",
                    kind,
                )
            backend = LocalStorageBackend(settings.storage_local_root or "uploads")

        _cached = backend
        return backend


def reset_storage_backend_for_tests() -> None:
    """Clear the memoised backend — used by tests that point the
    local backend at a temp directory per case."""
    global _cached
    with _lock:
        _cached = None
