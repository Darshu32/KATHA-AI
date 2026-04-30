"""Shared pytest fixtures for the KATHA-AI backend.

Two test tiers
--------------
- **unit** (default)        : fast, no external services. Mocks Redis/DB.
- **integration** (marker)   : runs against a real postgres + redis. Skipped
                                  unless ``KATHA_INTEGRATION_TESTS=1``.

Run units only::

    pytest tests/unit

Run everything against docker compose stack::

    KATHA_INTEGRATION_TESTS=1 pytest

Solo dev tip: keep unit tests fast (<1s each) so the full suite stays under
30 seconds. Anything slower belongs in integration.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio


# ─────────────────────────────────────────────────────────────────────
# Integration gate
# ─────────────────────────────────────────────────────────────────────


def _integration_enabled() -> bool:
    return os.environ.get("KATHA_INTEGRATION_TESTS", "").lower() in {"1", "true", "yes"}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration tests unless explicitly enabled."""
    if _integration_enabled():
        return
    skip = pytest.mark.skip(reason="set KATHA_INTEGRATION_TESTS=1 to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# ─────────────────────────────────────────────────────────────────────
# Asyncio policy
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def event_loop() -> Any:
    """Session-scoped event loop so async fixtures can be cached."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ─────────────────────────────────────────────────────────────────────
# Settings override
# ─────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _force_dev_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests always run with environment=dev so production guards don't trip."""
    monkeypatch.setenv("ENVIRONMENT", "dev")
    monkeypatch.setenv("DEBUG", "true")
    # Clear any cached settings from earlier imports.
    from app.config import get_settings
    get_settings.cache_clear()


# ─────────────────────────────────────────────────────────────────────
# Integration-only DB fixture
# ─────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[Any, None]:
    """Yields a transactional ``AsyncSession`` for integration tests.

    The session is rolled back at the end of every test, so tests can
    write freely without polluting the database. Migration state is the
    caller's responsibility (run ``alembic upgrade head`` before pytest).
    """
    if not _integration_enabled():
        pytest.skip("integration only")

    from app.database import async_session_factory, engine

    # Use a single connection wrapped in a top-level transaction so we
    # can roll back regardless of inner commits.
    async with engine.connect() as conn:
        trans = await conn.begin()
        async with async_session_factory(bind=conn) as session:
            try:
                yield session
            finally:
                await session.close()
        await trans.rollback()
