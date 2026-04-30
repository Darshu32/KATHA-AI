"""Redis-backed caching for repository reads.

Why this matters
----------------
Stages 1+ replace hardcoded Python dicts with DB lookups. A naive
implementation would hit Postgres on every LLM tool call — death by a
thousand round-trips. This module gives us:

- An ``async_cached`` decorator: drop-in for repository read methods.
- A namespaced key scheme: ``katha:cache:<namespace>:<arg-hash>``.
- TTL per call site (defaults to 5 min — long enough to amortize, short
  enough that admin price updates are visible "soon").
- Manual invalidation hooks so writes can purge stale entries.

Failure mode
------------
Redis going down must NOT break the app. ``async_cached`` falls back to
calling the wrapped function directly and logs a warning. Cache is a
performance feature, never a correctness feature.

Usage
-----
::

    @async_cached(namespace="materials", ttl=300)
    async def get_active_for(self, *, name: str, region: str, when: datetime):
        ...

    # On write:
    await invalidate("materials")  # nukes the entire materials namespace
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
from datetime import date, datetime
from typing import Any, Awaitable, Callable, Optional, TypeVar

import redis.asyncio as aioredis

from app.config import get_settings

T = TypeVar("T")

_log = logging.getLogger(__name__)
_settings = get_settings()

# A single client is fine — redis-py's async client is connection-pooled.
_client: Optional[aioredis.Redis] = None


def _get_client() -> aioredis.Redis:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            _settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=2.0,
            socket_connect_timeout=2.0,
        )
    return _client


# ─────────────────────────────────────────────────────────────────────────
# Key construction
# ─────────────────────────────────────────────────────────────────────────


def _stringify(value: Any) -> Any:
    """Make values JSON-serializable for hashing."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "id"):  # SQLAlchemy instance — use id only
        return f"{type(value).__name__}:{value.id}"
    return value


def _make_key(namespace: str, args: tuple, kwargs: dict) -> str:
    payload = {
        "args": [_stringify(a) for a in args[1:]],  # drop ``self``
        "kwargs": {k: _stringify(v) for k, v in sorted(kwargs.items())},
    }
    blob = json.dumps(payload, default=str, sort_keys=True)
    digest = hashlib.sha256(blob.encode()).hexdigest()[:16]
    return f"katha:cache:{namespace}:{digest}"


# ─────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────


def async_cached(
    *,
    namespace: str,
    ttl: int = 300,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Cache the result of an async repository read.

    The wrapped function MUST return JSON-serializable data, *not* a
    SQLAlchemy ORM instance. Repositories should typically convert ORM
    rows to plain dicts (or Pydantic models) before caching to avoid
    session-detachment headaches.

    On any Redis error the wrapped function is invoked directly.
    """

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            key = _make_key(namespace, args, kwargs)
            client = _get_client()

            # Try cache.
            try:
                cached = await client.get(key)
            except Exception as exc:  # pragma: no cover — Redis hiccup
                _log.warning("cache.get failed: %s", exc)
                cached = None

            if cached is not None:
                try:
                    return json.loads(cached)
                except json.JSONDecodeError:
                    # Treat as cache miss; continue to fetch fresh.
                    pass

            # Compute + populate.
            value = await fn(*args, **kwargs)
            try:
                await client.set(key, json.dumps(value, default=str), ex=ttl)
            except Exception as exc:  # pragma: no cover
                _log.warning("cache.set failed: %s", exc)
            return value

        return wrapper

    return decorator


async def invalidate(namespace: str) -> int:
    """Drop every cache entry under a namespace. Returns count deleted.

    Implementation note: we use SCAN rather than KEYS to avoid blocking
    Redis on large keyspaces.
    """
    client = _get_client()
    pattern = f"katha:cache:{namespace}:*"
    deleted = 0
    try:
        async for key in client.scan_iter(match=pattern, count=500):
            await client.delete(key)
            deleted += 1
    except Exception as exc:  # pragma: no cover
        _log.warning("cache.invalidate(%s) failed: %s", namespace, exc)
    return deleted


async def ping() -> bool:
    """Smoke-test Redis connectivity. Used by /health endpoint."""
    try:
        return await _get_client().ping()
    except Exception:
        return False
