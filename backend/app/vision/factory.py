"""Vision provider factory.

Picks :class:`AnthropicVisionProvider` when ``ANTHROPIC_API_KEY`` is
set, otherwise falls back to :class:`StubVisionProvider` and logs a
warning. Memoised so the SDK client is constructed once.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.config import get_settings
from app.vision.anthropic_vision import AnthropicVisionProvider
from app.vision.base import VisionProvider
from app.vision.stub import StubVisionProvider

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cached: Optional[VisionProvider] = None


def get_vision_provider() -> VisionProvider:
    """Return the configured provider — Anthropic when keyed, stub otherwise."""
    global _cached
    with _lock:
        if _cached is not None:
            return _cached

        settings = get_settings()
        if settings.has_anthropic_key:
            _cached = AnthropicVisionProvider(
                api_key=settings.anthropic_api_key,
                model=settings.vision_model or settings.anthropic_model,
            )
        else:
            log.warning(
                "ANTHROPIC_API_KEY not configured — using StubVisionProvider. "
                "Vision analyses will return canned fixtures, not real "
                "image understanding."
            )
            _cached = StubVisionProvider()
        return _cached


def reset_vision_provider_for_tests() -> None:
    """Clear the memoised provider — used by tests that inject their own."""
    global _cached
    with _lock:
        _cached = None
