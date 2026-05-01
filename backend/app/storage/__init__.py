"""Stage 7 — storage abstraction for uploaded assets.

KATHA needs to store binary uploads (site photos, hand sketches,
reference images) durably and retrieve them later for the vision
tools. We abstract the storage layer so two concrete backends
satisfy the same interface:

- :class:`LocalStorageBackend` — writes to a directory on disk.
  Production-fine for solo dev + integration tests; not for
  multi-instance deploys.
- :class:`S3StorageBackend` — boto3 against any S3-compatible API
  (AWS S3, Cloudflare R2, MinIO, …). Selected via
  ``settings.storage_backend = "s3"``.

The abstraction is intentionally narrow — ``put_bytes``,
``get_bytes``, ``delete``, ``presigned_url``. We don't wrap streaming
because architectural images are <25 MB and a synchronous bytes
transfer is fine.
"""

from app.storage.base import (
    StorageBackend,
    StorageError,
    StoredAsset,
)
from app.storage.factory import get_storage_backend
from app.storage.local import LocalStorageBackend
from app.storage.s3 import S3StorageBackend

__all__ = [
    "LocalStorageBackend",
    "S3StorageBackend",
    "StorageBackend",
    "StorageError",
    "StoredAsset",
    "get_storage_backend",
]
