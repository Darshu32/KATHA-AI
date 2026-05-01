"""Local-filesystem storage backend.

Writes to ``settings.storage_local_root`` (default ``./uploads``).
Suitable for solo dev + integration tests. Not for multi-instance
production — every instance has its own disk.

The ``key`` is treated as a relative path. We sanitise it to:

- forbid ``..`` traversal
- forbid absolute paths
- force lowercase
- replace anything outside ``[a-z0-9-_./]`` with ``_``

A path within ``settings.storage_local_root`` is the only place
writes can land.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from pathlib import Path
from typing import Optional

from app.storage.base import StorageBackend, StorageError, StoredAsset

log = logging.getLogger(__name__)


_SAFE_PATH_RE = re.compile(r"[^a-z0-9\-_/\.]+")


def _sanitise_key(key: str) -> str:
    """Reject path traversal + reserved chars; lowercase the result.

    The resulting key is **relative** (no leading slash) and contains
    only ``[a-z0-9-_./]``. Anything else is replaced with ``_``.
    """
    if not key:
        raise StorageError("storage key is empty")
    if "\x00" in key:
        raise StorageError("storage key contains null byte")
    key = key.strip().lstrip("/").lower()
    if ".." in key.split("/"):
        raise StorageError("storage key contains '..' traversal")
    key = _SAFE_PATH_RE.sub("_", key)
    if not key:
        raise StorageError("storage key reduced to empty after sanitisation")
    return key


class LocalStorageBackend(StorageBackend):
    """Filesystem-backed implementation.

    Files live under ``<root>/<key>``. Reads and writes are run via
    :func:`asyncio.to_thread` so the event loop isn't blocked on
    sync disk I/O.
    """

    name = "local"

    def __init__(self, root: str | os.PathLike[str]) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, key: str) -> Path:
        clean = _sanitise_key(key)
        full = (self._root / clean).resolve()
        # Defence in depth — even after sanitising, confirm the
        # resolved path is still under root.
        if self._root not in full.parents and full != self._root:
            raise StorageError(f"resolved path escapes storage root: {full}")
        return full

    async def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        mime_type: str,
    ) -> StoredAsset:
        target = self._resolve(key)
        target.parent.mkdir(parents=True, exist_ok=True)

        def _write() -> int:
            with target.open("wb") as fh:
                return fh.write(data)

        try:
            written = await asyncio.to_thread(_write)
        except OSError as exc:
            raise StorageError(f"local write failed: {exc}") from exc

        return StoredAsset(
            key=_sanitise_key(key),
            size_bytes=int(written),
            mime_type=mime_type,
        )

    async def get_bytes(self, key: str) -> bytes:
        target = self._resolve(key)
        if not target.exists():
            raise StorageError(f"key not found: {key}")

        def _read() -> bytes:
            with target.open("rb") as fh:
                return fh.read()

        try:
            return await asyncio.to_thread(_read)
        except OSError as exc:
            raise StorageError(f"local read failed: {exc}") from exc

    async def delete(self, key: str) -> None:
        target = self._resolve(key)
        if not target.exists():
            return  # idempotent
        try:
            await asyncio.to_thread(target.unlink)
        except OSError as exc:
            raise StorageError(f"local delete failed: {exc}") from exc

    async def exists(self, key: str) -> bool:
        target = self._resolve(key)
        return await asyncio.to_thread(target.exists)

    async def presigned_url(
        self,
        key: str,
        *,
        expires_seconds: int = 3600,
    ) -> Optional[str]:
        # Local disk has no presigning — clients fall back to the
        # ``GET /uploads/{id}/content`` proxy route.
        return None
