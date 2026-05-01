"""Vision provider abstraction.

Why an ABC?
-----------
Two real implementations + one stub:

- :class:`AnthropicVisionProvider` — Claude Vision (production).
- :class:`StubVisionProvider` — deterministic fixture (tests).
- *Future* — OpenAI Vision (fallback path).

The ABC pins the contract:

- One async method ``analyze``.
- Inputs are a ``VisionRequest`` describing one image (or set, for
  ``mood_board``) plus the system prompt + JSON output schema.
- Output is a ``VisionResult`` with the parsed dict and the model's
  raw text reply (for debugging).

We don't expose streaming — vision analyses are short and benefit
from a single round-trip.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


class VisionError(RuntimeError):
    """Raised when the provider cannot return a parsed result."""


@dataclass
class VisionImage:
    """One image input — bytes plus the MIME type."""

    data: bytes
    mime_type: str
    label: str = ""
    """Optional human label so multi-image prompts can refer to
    "image 1 (north view)" etc."""


@dataclass
class VisionRequest:
    """One vision call — what to send to the provider."""

    images: list[VisionImage]
    system_prompt: str
    user_message: str
    output_schema: dict[str, Any]
    """A JSON schema for the structured output. Providers that
    natively support response-format JSON-schema use it; the stub
    ignores it (and returns whatever fixture matches the purpose)."""

    purpose: str = ""
    """Name of the purpose for telemetry / stub dispatch."""

    max_tokens: int = 1500
    temperature: float = 0.2


@dataclass
class VisionResult:
    """One vision call's parsed output + provenance."""

    parsed: dict[str, Any]
    raw_text: str = ""
    model: str = ""
    provider_name: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class VisionProvider(ABC):
    """Async vision provider — one shot, structured output."""

    name: str = "abstract"

    @abstractmethod
    async def analyze(self, request: VisionRequest) -> VisionResult:
        """Send the request to the provider, parse the JSON reply.

        Implementations promise:

        - Empty ``request.images`` raises :class:`VisionError`.
        - The returned ``VisionResult.parsed`` matches
          ``request.output_schema`` (best-effort — providers can
          drift, callers should tolerate missing optional fields).
        - Any provider failure raises :class:`VisionError` with the
          underlying exception attached. We never silently return
          empty / fabricated data.
        """
        ...
