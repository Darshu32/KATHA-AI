"""Adapter registry — single instance per process.

Mirrors the agent-tool registry pattern (:mod:`app.agents.tool`):
adapters register themselves at import time, the orchestrator and
admin routes look them up by ``feed_source`` slug.

The registry is *settings-aware*. ``register_default_adapters()``
selects the live or stub variant of every adapter based on
``settings.live_feeds_enabled`` so tests get deterministic stubs by
default and prod gets real HTTP calls without per-callsite branching.
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.config import get_settings
from app.feeds.base import FeedAdapter


class FeedRegistry:
    """In-process registry of feed adapters keyed by ``feed_source``."""

    def __init__(self) -> None:
        self._adapters: dict[str, FeedAdapter] = {}

    def register(self, adapter: FeedAdapter) -> None:
        if not adapter.feed_source:
            raise ValueError("Adapter missing feed_source")
        self._adapters[adapter.feed_source] = adapter

    def unregister(self, feed_source: str) -> None:
        self._adapters.pop(feed_source, None)

    def get(self, feed_source: str) -> Optional[FeedAdapter]:
        return self._adapters.get(feed_source)

    def all(self) -> list[FeedAdapter]:
        return list(self._adapters.values())

    def feed_sources(self) -> list[str]:
        return sorted(self._adapters.keys())

    def clear(self) -> None:
        self._adapters.clear()


_registry_singleton: Optional[FeedRegistry] = None


def get_registry() -> FeedRegistry:
    """Process-wide singleton. Lazy so tests can monkey-patch."""
    global _registry_singleton
    if _registry_singleton is None:
        _registry_singleton = FeedRegistry()
        _bootstrap_default_adapters(_registry_singleton)
    return _registry_singleton


def reset_registry() -> None:
    """Clear and re-register default adapters. Test-only."""
    global _registry_singleton
    _registry_singleton = None


def _bootstrap_default_adapters(reg: FeedRegistry) -> None:
    """Register the bundled adapters on first ``get_registry()`` call.

    Selection is driven by ``settings.live_feeds_enabled``: when
    False (the default — and what the test suite uses) every adapter
    is the deterministic stub variant. When True each adapter
    constructs its live HTTP client.
    """
    settings = get_settings()
    use_live = settings.live_feeds_enabled

    # Local imports to avoid circular import at module load time.
    from app.feeds.adapters import (
        asian_paints,
        fx,
        gst,
        jaquar,
        kohler,
        mcx,
    )

    for module in (mcx, fx, gst, jaquar, kohler, asian_paints):
        adapter = module.build_adapter(settings, live=use_live)
        reg.register(adapter)


def register_for_test(adapters: Iterable[FeedAdapter]) -> None:
    """Replace registry contents with a custom set. Test-only."""
    reset_registry()
    reg = get_registry()
    reg.clear()
    for a in adapters:
        reg.register(a)
