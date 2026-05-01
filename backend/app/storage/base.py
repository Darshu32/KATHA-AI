"""Storage abstraction — :class:`StorageBackend` ABC and shared types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class StorageError(RuntimeError):
    """Raised when a storage operation cannot complete (write/read/delete)."""


@dataclass
class StoredAsset:
    """Result of a successful ``put_bytes`` call.

    The ``key`` is opaque to callers — they pass it back to
    :meth:`StorageBackend.get_bytes` / :meth:`StorageBackend.delete`.
    For the local backend the key is a path-safe relative path; for
    S3 it's the object key under the configured bucket.
    """

    key: str
    size_bytes: int
    mime_type: str


class StorageBackend(ABC):
    """Abstract storage interface.

    Implementations promise:

    - ``put_bytes`` is idempotent for the same ``key`` — re-writing
      replaces.
    - ``get_bytes`` raises :class:`StorageError` when the key is
      missing.
    - ``delete`` is idempotent — silently succeeds when key is missing.
    - ``presigned_url`` returns ``None`` when the backend doesn't
      support presigning (e.g. local-disk in dev).
    """

    name: str = "abstract"

    @abstractmethod
    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        mime_type: str,
    ) -> StoredAsset:
        """Persist bytes under ``key``. Returns the :class:`StoredAsset`."""
        ...

    @abstractmethod
    async def get_bytes(self, key: str) -> bytes:
        """Read bytes back. Raises :class:`StorageError` when missing."""
        ...

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove the stored object. Idempotent — no error if missing."""
        ...

    async def presigned_url(
        self,
        key: str,
        *,
        expires_seconds: int = 3600,
    ) -> Optional[str]:
        """Return a presigned URL the client can fetch directly.

        Returns ``None`` for backends that can't generate one — the
        caller falls back to the proxy route ``GET /uploads/{id}/content``.
        """
        return None

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """Cheap existence check. Used by the upload route to confirm
        a write landed before the DB row is committed."""
        ...
