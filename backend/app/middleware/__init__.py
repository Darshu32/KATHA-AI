"""HTTP middlewares + shared route dependencies.

Stage 13 grew this into a package; the auth dependency that lived
in ``middleware.py`` is re-exported here so existing imports
(``from app.middleware import get_current_user``) keep working
unchanged.
"""

from __future__ import annotations

# ── Auth dependency (Stage 0) ────────────────────────────────────────
# Re-exported from the legacy single-file module so callers don't
# need to update their imports.
from fastapi import Depends, HTTPException, Request, status  # noqa: F401
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401

from app.database import get_db
from app.models.orm import User
from app.services.auth_service import (
    decode_access_token,
    get_or_create_dev_user,
)


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT, return the User ORM instance.

    Original lives in ``app.middleware`` (single-file module); this
    re-export keeps the package import path stable while allowing
    Stage 13 to grow ``app.middleware.rate_limit`` etc.
    """
    if credentials is None:
        return await get_or_create_dev_user(db)

    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )

    from sqlalchemy import select

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    return user


# ── Stage 13 middlewares ─────────────────────────────────────────────
from app.middleware.rate_limit import (  # noqa: E402, F401
    RateLimitConfig,
    RateLimitMiddleware,
    RateLimitTier,
    classify_request,
)


__all__ = [
    "get_current_user",
    "RateLimitConfig",
    "RateLimitMiddleware",
    "RateLimitTier",
    "classify_request",
]
