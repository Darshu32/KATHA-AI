"""Anthropic Claude Vision provider.

Uses the standard ``messages`` API with image content blocks. Each
:class:`VisionRequest` carries 1+ images and a JSON output schema —
we encode the images as base64 and prepend them to the user message
in the order supplied.

JSON-mode contract
------------------
Anthropic doesn't yet have a strict JSON-schema mode like OpenAI's
``response_format``, so we lean on the *system prompt* to ask for
JSON only and parse defensively. The schema in
``VisionRequest.output_schema`` is *included verbatim* in the
system prompt so the model knows exactly what shape to return.

Failures
--------
- Empty images → :class:`VisionError` (caller bug).
- API error → re-raised as :class:`VisionError`.
- Reply isn't valid JSON → parse a balanced JSON object out of the
  text. If that fails, raise :class:`VisionError`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Optional

from app.vision.base import (
    VisionError,
    VisionProvider,
    VisionRequest,
    VisionResult,
)

log = logging.getLogger(__name__)


def _extract_json(text: str) -> Optional[dict[str, Any]]:
    """Best-effort JSON parse from a chatty reply.

    Tries a strict ``json.loads`` first, then scans for the first
    balanced top-level ``{...}`` object.
    """
    text = (text or "").strip()
    if not text:
        return None
    # Strip code fences if present.
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1:]
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back to a brace-counting scan (the regex above won't work
    # in all Python versions because it uses recursion).
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start != -1:
                snippet = text[start: i + 1]
                try:
                    return json.loads(snippet)
                except json.JSONDecodeError:
                    start = -1
                    continue
    return None


class AnthropicVisionProvider(VisionProvider):
    """Live Claude Vision via the Anthropic SDK.

    Lazy-imports ``anthropic`` so dev environments without the SDK
    can still import the rest of the codebase.
    """

    name = "anthropic_vision"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise VisionError(
                "AnthropicVisionProvider requires an api_key — "
                "set ANTHROPIC_API_KEY."
            )
        try:
            from anthropic import AsyncAnthropic
        except ImportError as exc:  # pragma: no cover
            raise VisionError(
                "anthropic SDK is not installed — `pip install anthropic`."
            ) from exc

        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model
        self._timeout = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    async def analyze(self, request: VisionRequest) -> VisionResult:
        if not request.images:
            raise VisionError("VisionRequest has no images")

        # Build the system prompt: the caller-supplied prose +
        # an explicit JSON-shape contract.
        schema_json = json.dumps(request.output_schema, indent=2)
        system = (
            f"{request.system_prompt}\n\n"
            "Respond with **JSON only** matching exactly this schema. "
            "No prose, no markdown fences. Required fields are mandatory; "
            "stick to the listed enum values where given.\n\n"
            f"OUTPUT_SCHEMA:\n{schema_json}"
        )

        # Anthropic content blocks: a list of ``{type: image, source: ...}``
        # blocks followed by the user-text block.
        content: list[dict[str, Any]] = []
        for img in request.images:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": img.mime_type,
                    "data": base64.b64encode(img.data).decode("ascii"),
                },
            })
            if img.label:
                content.append({"type": "text", "text": f"[{img.label}]"})
        content.append({"type": "text", "text": request.user_message})

        try:
            resp = await asyncio.wait_for(
                self._client.messages.create(
                    model=self._model,
                    system=system,
                    messages=[{"role": "user", "content": content}],
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise VisionError(
                f"Anthropic vision call timed out after {self._timeout}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise VisionError(f"Anthropic vision call failed: {exc}") from exc

        # Extract text from the (possibly multi-block) reply.
        raw_text_parts: list[str] = []
        for block in getattr(resp, "content", None) or []:
            text = getattr(block, "text", None)
            if isinstance(text, str):
                raw_text_parts.append(text)
        raw_text = "".join(raw_text_parts).strip()

        parsed = _extract_json(raw_text)
        if parsed is None:
            raise VisionError(
                "Anthropic vision reply was not valid JSON: "
                f"{raw_text[:200]!r}"
            )

        usage = getattr(resp, "usage", None)
        return VisionResult(
            parsed=parsed,
            raw_text=raw_text,
            model=self._model,
            provider_name=self.name,
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0) if usage else 0,
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0) if usage else 0,
        )
