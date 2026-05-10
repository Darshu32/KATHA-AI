"""Object-storage adapter — local filesystem for prototype, S3-shaped API.

The image-generation pipeline used to embed each render as a
base-64 ``data:`` URI in both ``GeneratedAsset.storage_key`` and the
response payload — the same multi-hundred-KB blob travelled the
network and the database round-trip on every read. This module
replaces that with a proper object-storage surface:

  • Raw bytes live on disk under ``STORAGE_ROOT``.
  • The DB stores only the short *key* (e.g. ``renders/abc/v01-uuid.png``).
  • The frontend reads bytes through ``GET /api/v1/assets/{key}`` — a
    proper URL that browsers can cache and CDNs can front later.

The public API (``save_bytes``, ``read_bytes``, ``make_key``,
``key_to_url``) is intentionally S3-shaped, so a future migration to
R2 / S3 / GCS is a one-module swap — call sites and DB rows don't
change.

Path-traversal hardening
------------------------
``key`` is treated as an untrusted relative path. Every resolved
filesystem location is verified to sit *under* ``STORAGE_ROOT`` so a
malicious key like ``../../../../etc/passwd`` can't escape the
sandbox. The HTTP route at /assets/{key:path} therefore can't be
weaponised into a generic file-read primitive.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Default storage root sits next to the running backend. Override via
# the ``STORAGE_ROOT`` environment variable when you deploy somewhere
# that has writable persistent disk at a known location (or migrate
# this module to an S3 client).
_DEFAULT_ROOT = Path(__file__).resolve().parent.parent.parent / "storage"

# Whitelist for key path components — letters, digits, hyphen,
# underscore, dot. We replace anything else with '-' so an exotic
# slug ("modern · italian") yields a clean key.
_KEY_SAFE = re.compile(r"[^a-zA-Z0-9_\-.]")


def storage_root() -> Path:
    root = os.getenv("STORAGE_ROOT", "").strip()
    return Path(root).expanduser().resolve() if root else _DEFAULT_ROOT.resolve()


def _safe_component(value: str, max_len: int = 120) -> str:
    """Sanitise one path segment — strips path separators, exotic chars,
    and length-caps. An empty result becomes 'x' so the join never
    produces a zero-length segment."""
    cleaned = _KEY_SAFE.sub("-", value).strip("-.") or "x"
    return cleaned[:max_len]


def make_key(*parts: str, ext: str = "png") -> str:
    """Build a key like ``renders/{project_id}/{version}-{uuid}.png``.

    A short UUID suffix is always appended so two renders against the
    same version can't collide (e.g. theme-switch + initial both
    landing on v01 in race conditions, or an admin force-rerendering
    an existing version).
    """
    safe_parts = [_safe_component(p) for p in parts if p is not None]
    safe_parts.append(uuid.uuid4().hex[:12])
    safe_ext = _safe_component(ext.lstrip("."), max_len=8) or "bin"
    return "/".join(safe_parts) + "." + safe_ext


def _resolve_safe(key: str) -> Path:
    """Resolve key → absolute path, ensuring it stays under storage root."""
    if not key or key.startswith("/"):
        raise ValueError(f"Invalid storage key: {key!r}")
    root = storage_root()
    full = (root / key).resolve()
    # The resolved path must be the root itself or strictly under it.
    if full != root and root not in full.parents:
        raise ValueError(f"Path traversal blocked: {key!r}")
    return full


async def save_bytes(key: str, data: bytes) -> None:
    """Persist raw bytes at the given key. Creates parent directories
    on demand. Writes are atomic via a temp-file + rename, so a
    partial write never leaves a half-written render visible to
    readers.
    """
    full = _resolve_safe(key)
    full.parent.mkdir(parents=True, exist_ok=True)
    tmp = full.with_suffix(full.suffix + ".part")
    try:
        await asyncio.to_thread(tmp.write_bytes, data)
        await asyncio.to_thread(os.replace, tmp, full)
    finally:
        # Best-effort cleanup if the rename never happened (disk full,
        # permission flap). The .part file might linger; that's fine.
        if tmp.exists() and not full.exists():
            try:
                await asyncio.to_thread(tmp.unlink)
            except OSError:
                pass
    logger.debug("Storage write: key=%s bytes=%d", key, len(data))


async def read_bytes(key: str) -> bytes | None:
    """Return the bytes at ``key`` or ``None`` if absent / unreadable."""
    try:
        full = _resolve_safe(key)
    except ValueError as exc:
        logger.warning("Rejected key on read: %s", exc)
        return None
    if not full.is_file():
        return None
    try:
        return await asyncio.to_thread(full.read_bytes)
    except OSError as exc:
        logger.warning("Storage read failed for %s: %s", key, exc)
        return None


def key_to_url(key: str) -> str:
    """The URL the frontend uses to GET this asset. Public route, no
    auth required — the keys themselves are unguessable (UUID suffix),
    which is the prototype's discoverability barrier. When a real
    permissioning model lands, swap this for a signed-URL emitter."""
    return f"/api/v1/assets/{key}"
