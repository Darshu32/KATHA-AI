"""Vision provider factory.

Selection order:
1. :class:`OpenAIVisionProvider` when ``OPENAI_API_KEY`` is set — the
   production path. Vision runs on the same key as the agent runtime.
2. :class:`AnthropicVisionProvider` when only ``ANTHROPIC_API_KEY`` is
   set — optional fallback for installs that still key Anthropic.
3. :class:`StubVisionProvider` otherwise (canned fixtures; tests).

Memoised so the SDK client is constructed once.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.config import get_settings
from app.vision.anthropic_vision import AnthropicVisionProvider
from app.vision.base import VisionProvider
from app.vision.openai_vision import OpenAIVisionProvider
from app.vision.stub import StubVisionProvider

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cached: Optional[VisionProvider] = None


def get_vision_provider() -> VisionProvider:
    """Return the configured provider — OpenAI when keyed, else Anthropic, else stub."""
    global _cached
    with _lock:
        if _cached is not None:
            return _cached

        settings = get_settings()
        if settings.has_openai_key:
            _cached = OpenAIVisionProvider(
                api_key=settings.openai_api_key,
                model=settings.vision_model or settings.openai_model,
                base_url=settings.openai_base_url or None,
            )
        elif settings.has_anthropic_key:
            _cached = AnthropicVisionProvider(
                api_key=settings.anthropic_api_key,
                model=settings.anthropic_model,
            )
        else:
            log.warning(
                "No OPENAI_API_KEY or ANTHROPIC_API_KEY configured — using "
                "StubVisionProvider. Vision analyses will return canned "
                "fixtures, not real image understanding."
            )
            _cached = StubVisionProvider()
        return _cached


def reset_vision_provider_for_tests() -> None:
    """Clear the memoised provider — used by tests that inject their own."""
    global _cached
    with _lock:
        _cached = None
