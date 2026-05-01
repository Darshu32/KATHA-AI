"""Stage 13 — Redis sliding-window rate limiting middleware.

Three buckets keyed by (actor, tier) keep abuse contained without
breaking normal usage:

==========================  ==================  ===========================================
Tier                         Default limit       Routes that match
==========================  ==================  ===========================================
``llm`` (heavy)              **60 req/min**     Anything calling Claude/OpenAI: ``/agent``,
                                                 generation, specs, drawings, recommendations.
``write`` (state-changing)   **100 req/min**    POST/PUT/DELETE on persistent resources.
``read`` (cheap)             **600 req/min**    Everything else: GET on projects, decisions,
                                                 chat history, knowledge search.
==========================  ==================  ===========================================

Storage
-------
Redis sorted set per ``(tier, actor_id)``. Each request adds a
timestamped member; the middleware then trims members older than
the window and counts what remains. ZRANGEBYSCORE + ZADD + ZCARD =
3 commands per request — pipelined into one round-trip.

Soft-fail
---------
If Redis is unreachable the middleware **does not** block the
request — it logs a warning and lets the call through. Rate
limiting is a defence layer; downtime in the limiter must not
become downtime in the API.

Per-route override
------------------
Routes that need bespoke limits can mark themselves with
``request.state.rate_limit_tier = "llm"`` (or any of the tiers)
inside a dependency. The middleware honours the override; without
it, classification falls back to :func:`classify_request`.

Identity
--------
The actor key is ``user_id`` when ``request.state.user`` is set
(via the auth dependency); otherwise the client IP. ``X-Forwarded-
For`` is honoured if the front proxy is trusted (Stage 13 default
trusts the first hop only — adjust in production if you have
multiple proxies).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.observability.error_codes import ErrorCode
from app.observability.error_envelope import build_envelope


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Tier classification
# ─────────────────────────────────────────────────────────────────────


class RateLimitTier(str, Enum):
    LLM = "llm"
    WRITE = "write"
    READ = "read"


# Path-prefix → tier hints. Routes can override per-request via
# ``request.state.rate_limit_tier``. Keep this short — most routes
# fall through to the method-based default below.
_PATH_PREFIX_HINTS: tuple[tuple[str, RateLimitTier], ...] = (
    # LLM-heavy.
    ("/api/v1/agent", RateLimitTier.LLM),
    ("/api/v1/generation", RateLimitTier.LLM),
    ("/api/v1/specs", RateLimitTier.LLM),
    ("/api/v1/drawings", RateLimitTier.LLM),
    ("/api/v1/diagrams", RateLimitTier.LLM),
    ("/api/v1/working_drawings", RateLimitTier.LLM),
    ("/api/v1/parametric", RateLimitTier.LLM),
    # Brief intake hits the LLM for the architect-brief endpoint.
    ("/api/v1/brief/architect", RateLimitTier.LLM),
    # Write-heavy on uploads.
    ("/api/v1/uploads", RateLimitTier.WRITE),
)


def classify_request(request: Request) -> RateLimitTier:
    """Pick a tier for one request.

    1. If ``request.state.rate_limit_tier`` was set by an upstream
       dependency, honour it.
    2. Match against :data:`_PATH_PREFIX_HINTS`.
    3. Else: ``write`` for non-GET methods, ``read`` for GET / HEAD
       / OPTIONS.
    """
    explicit = getattr(request.state, "rate_limit_tier", None)
    if isinstance(explicit, RateLimitTier):
        return explicit
    if isinstance(explicit, str):
        try:
            return RateLimitTier(explicit)
        except ValueError:
            pass

    path = request.url.path
    for prefix, tier in _PATH_PREFIX_HINTS:
        if path.startswith(prefix):
            return tier

    method = (request.method or "").upper()
    if method in {"GET", "HEAD", "OPTIONS"}:
        return RateLimitTier.READ
    return RateLimitTier.WRITE


# ─────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RateLimitConfig:
    """Per-tier limits + window. All counts are per actor per window."""

    window_seconds: int = 60
    limits: dict[RateLimitTier, int] = None  # type: ignore[assignment]
    bypass_paths: frozenset[str] = frozenset({"/health", "/docs", "/redoc",
                                              "/openapi.json"})

    @classmethod
    def defaults(cls) -> "RateLimitConfig":
        return cls(
            window_seconds=60,
            limits={
                RateLimitTier.LLM: 60,
                RateLimitTier.WRITE: 100,
                RateLimitTier.READ: 600,
            },
        )

    def limit_for(self, tier: RateLimitTier) -> int:
        return (self.limits or {}).get(tier, 600)


# ─────────────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────────────


def _actor_key(request: Request) -> str:
    """Pick the rate-limit key for one request.

    Prefers authenticated user id when an upstream dependency set
    ``request.state.user``; otherwise the (trusted) client IP.
    """
    user = getattr(request.state, "user", None)
    if user is not None and getattr(user, "id", None):
        return f"user:{user.id}"
    # Trust X-Forwarded-For only one hop deep — operator can adjust.
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        ip = fwd.split(",", 1)[0].strip()
        if ip:
            return f"ip:{ip}"
    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "ip:unknown"


# ─────────────────────────────────────────────────────────────────────
# Middleware
# ─────────────────────────────────────────────────────────────────────


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window limiter. Soft-fails if Redis is down.

    The Redis client factory is injected so tests can swap it for an
    in-memory fake. The default factory lazily imports ``redis.asyncio``
    so the middleware doesn't break when Redis isn't installed in a
    minimal env (it'll soft-fail and log).
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        config: Optional[RateLimitConfig] = None,
        redis_url: Optional[str] = None,
        redis_factory: Optional[Callable[[], "object"]] = None,
        classifier: Callable[[Request], RateLimitTier] = classify_request,
    ) -> None:
        super().__init__(app)
        self.config = config or RateLimitConfig.defaults()
        self._redis_url = redis_url
        self._redis_factory = redis_factory
        self._classifier = classifier
        self._redis_client = None  # lazy
        self._redis_failed = False  # remember soft-fail to throttle log spam

    async def _redis(self):
        if self._redis_client is not None:
            return self._redis_client
        if self._redis_failed:
            return None
        if self._redis_factory is not None:
            try:
                self._redis_client = self._redis_factory()
                return self._redis_client
            except Exception as exc:  # noqa: BLE001
                logger.warning("rate_limit.redis_factory_failed: %s", exc)
                self._redis_failed = True
                return None
        if not self._redis_url:
            self._redis_failed = True
            return None
        try:
            from redis import asyncio as redis_asyncio  # type: ignore[import-not-found]

            self._redis_client = redis_asyncio.from_url(
                self._redis_url, decode_responses=True,
            )
            return self._redis_client
        except Exception as exc:  # noqa: BLE001
            logger.warning("rate_limit.redis_connect_failed: %s", exc)
            self._redis_failed = True
            return None

    async def _is_over_limit(
        self,
        *,
        actor_key: str,
        tier: RateLimitTier,
    ) -> tuple[bool, int, int]:
        """Returns ``(over_limit, current_count, limit)``.

        On Redis failure, returns ``(False, 0, limit)`` — soft-fail.
        """
        limit = self.config.limit_for(tier)
        client = await self._redis()
        if client is None:
            return False, 0, limit

        bucket_key = f"katha:rate:{tier.value}:{actor_key}"
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms - (self.config.window_seconds * 1000)
        try:
            pipe = client.pipeline()
            pipe.zremrangebyscore(bucket_key, 0, cutoff_ms)
            pipe.zadd(bucket_key, {f"{now_ms}:{actor_key}": now_ms})
            pipe.zcard(bucket_key)
            pipe.expire(bucket_key, self.config.window_seconds + 5)
            results = await pipe.execute()
            count = int(results[2] or 0)
            return count > limit, count, limit
        except Exception as exc:  # noqa: BLE001
            logger.warning("rate_limit.redis_op_failed: %s", exc)
            self._redis_failed = True
            return False, 0, limit

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in self.config.bypass_paths:
            return await call_next(request)

        tier = self._classifier(request)
        actor_key = _actor_key(request)

        over_limit, count, limit = await self._is_over_limit(
            actor_key=actor_key, tier=tier,
        )
        if over_limit:
            return JSONResponse(
                status_code=429,
                content=build_envelope(
                    code=ErrorCode.RATE_LIMITED,
                    message=(
                        f"Rate limit exceeded for tier={tier.value}: "
                        f"{count}/{limit} per {self.config.window_seconds}s "
                        "window. Slow down and retry."
                    ),
                    details=[{"field": "tier", "message": tier.value}],
                ),
                headers={
                    "X-RateLimit-Tier": tier.value,
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Window": str(self.config.window_seconds),
                    "Retry-After": str(self.config.window_seconds),
                },
            )

        response = await call_next(request)

        # Stamp telemetry headers so clients can self-throttle.
        response.headers["X-RateLimit-Tier"] = tier.value
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        response.headers["X-RateLimit-Window"] = str(self.config.window_seconds)
        return response


__all__ = [
    "RateLimitConfig",
    "RateLimitMiddleware",
    "RateLimitTier",
    "classify_request",
]
