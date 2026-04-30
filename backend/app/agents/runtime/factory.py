"""Provider selection.

Picks the right :class:`AgentProvider` based on configured API keys.
Stage 2 ships **Anthropic only** as the live provider — OpenAI fallback
is wired in but raises ``NotImplementedError`` until Stage 5 (when we
need it for cost-balancing trivial subtasks).
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.runtime.anthropic import AnthropicProvider
from app.agents.runtime.base import AgentProvider
from app.config import get_settings

log = logging.getLogger(__name__)


class _OpenAIPlaceholder(AgentProvider):
    """Stage 2 placeholder — Stage 5 implements OpenAI tool-use."""

    name = "openai"

    async def stream(self, messages, config):  # type: ignore[override]
        raise NotImplementedError(
            "OpenAI agent provider not implemented in Stage 2. "
            "Set ANTHROPIC_API_KEY or wait for Stage 5."
        )
        yield  # type: ignore[unreachable]  # makes it an async generator


_anthropic_singleton: Optional[AnthropicProvider] = None


def get_provider(name: Optional[str] = None) -> AgentProvider:
    """Return the configured :class:`AgentProvider`.

    Selection rules
    ---------------
    - Explicit ``name`` (``"anthropic"`` | ``"openai"``) wins.
    - Else: Anthropic if ``ANTHROPIC_API_KEY`` is set, else placeholder.
    """
    settings = get_settings()
    target = (name or _auto_select(settings)).lower()

    if target == "anthropic":
        global _anthropic_singleton
        if _anthropic_singleton is None:
            _anthropic_singleton = AnthropicProvider()
        return _anthropic_singleton

    if target == "openai":
        return _OpenAIPlaceholder()

    raise ValueError(f"Unknown agent provider: {target!r}")


def _auto_select(settings) -> str:
    if settings.has_anthropic_key:
        return "anthropic"
    log.warning(
        "No ANTHROPIC_API_KEY configured — agent runs will fail until set."
    )
    return "anthropic"  # Default surface still anthropic so error is clear.
