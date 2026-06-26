"""Provider selection.

Picks the right :class:`AgentProvider` based on configured API keys.

Platform decision (Option B): **OpenAI is the primary agent runtime**
for chat + reasoning. Anthropic remains wired in as a fallback/secondary
provider, but the Anthropic SDK's main job on the platform is now the
vision provider (:mod:`app.vision.anthropic_vision`), not the agent
loop.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.agents.runtime.anthropic import AnthropicProvider
from app.agents.runtime.base import AgentProvider
from app.agents.runtime.openai import OpenAIProvider
from app.config import get_settings

log = logging.getLogger(__name__)


_openai_singleton: Optional[OpenAIProvider] = None
_anthropic_singleton: Optional[AnthropicProvider] = None


def get_provider(name: Optional[str] = None) -> AgentProvider:
    """Return the configured :class:`AgentProvider`.

    Selection rules
    ---------------
    - Explicit ``name`` (``"openai"`` | ``"anthropic"``) wins.
    - Else: OpenAI if ``OPENAI_API_KEY`` is set; otherwise fall back to
      Anthropic if its key is set; otherwise default to OpenAI so the
      "missing key" error surfaced downstream is the expected one.
    """
    settings = get_settings()
    target = (name or _auto_select(settings)).lower()

    if target == "openai":
        global _openai_singleton
        if _openai_singleton is None:
            _openai_singleton = OpenAIProvider()
        return _openai_singleton

    if target == "anthropic":
        global _anthropic_singleton
        if _anthropic_singleton is None:
            _anthropic_singleton = AnthropicProvider()
        return _anthropic_singleton

    raise ValueError(f"Unknown agent provider: {target!r}")


def _auto_select(settings) -> str:
    if settings.has_openai_key:
        return "openai"
    if settings.has_anthropic_key:
        log.info(
            "No OPENAI_API_KEY — falling back to Anthropic agent provider."
        )
        return "anthropic"
    log.warning(
        "No OPENAI_API_KEY configured — agent runs will fail until set."
    )
    return "openai"  # Default surface stays OpenAI so the error is clear.
