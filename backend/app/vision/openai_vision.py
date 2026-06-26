"""OpenAI Vision provider — the **production** vision backend.

Uses the Chat Completions API with image content blocks. Each
:class:`VisionRequest` carries 1+ images and a JSON output schema —
we encode the images as base64 ``data:`` URIs and prepend them to the
user message in the order supplied.

JSON-mode contract
------------------
OpenAI supports ``response_format={"type": "json_object"}`` which
guarantees syntactically valid JSON. We *also* embed the requested
schema verbatim in the system prompt so the model returns the right
*shape*, and parse defensively in case a model ignores either signal.

Why OpenAI for vision
---------------------
Vision was migrated off Anthropic so the platform runs on two keys:
``OPENAI_API_KEY`` (chat + vision) and ``GEMINI_API_KEY`` (image gen).
The ``anthropic`` SDK and :class:`AnthropicVisionProvider` remain in
the tree as an optional fallback, but no Anthropic key is required.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from typing import Any, Optional

from app.vision.anthropic_vision import _extract_json
from app.vision.base import (
    VisionError,
    VisionProvider,
    VisionRequest,
    VisionResult,
)

log = logging.getLogger(__name__)


class OpenAIVisionProvider(VisionProvider):
    """Live GPT Vision via the OpenAI SDK.

    Lazy-imports ``openai`` so dev environments without the SDK can
    still import the rest of the codebase.
    """

    name = "openai_vision"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        base_url: Optional[str] = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key.strip():
            raise VisionError(
                "OpenAIVisionProvider requires an api_key — "
                "set OPENAI_API_KEY."
            )
        try:
            from openai import AsyncOpenAI
        except ImportError as exc:  # pragma: no cover
            raise VisionError(
                "openai SDK is not installed — `pip install openai`."
            ) from exc

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._timeout = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    async def analyze(self, request: VisionRequest) -> VisionResult:
        if not request.images:
            raise VisionError("VisionRequest has no images")

        # Build the system prompt: the caller-supplied prose + an
        # explicit JSON-shape contract. The literal word "json" must
        # appear somewhere in the prompt for ``json_object`` mode.
        schema_json = json.dumps(request.output_schema, indent=2)
        system = (
            f"{request.system_prompt}\n\n"
            "Respond with **JSON only** matching exactly this schema. "
            "No prose, no markdown fences. Required fields are mandatory; "
            "stick to the listed enum values where given.\n\n"
            f"OUTPUT_SCHEMA:\n{schema_json}"
        )

        # OpenAI content blocks: text + ``image_url`` blocks carrying a
        # base64 data URI. Images are prepended in the supplied order.
        content: list[dict[str, Any]] = []
        for img in request.images:
            b64 = base64.b64encode(img.data).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{img.mime_type};base64,{b64}"},
            })
            if img.label:
                content.append({"type": "text", "text": f"[{img.label}]"})
        content.append({"type": "text", "text": request.user_message})

        try:
            resp = await asyncio.wait_for(
                self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": content},
                    ],
                    max_tokens=request.max_tokens,
                    temperature=request.temperature,
                    response_format={"type": "json_object"},
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise VisionError(
                f"OpenAI vision call timed out after {self._timeout}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise VisionError(f"OpenAI vision call failed: {exc}") from exc

        choices = getattr(resp, "choices", None) or []
        raw_text = ""
        if choices:
            message = getattr(choices[0], "message", None)
            raw_text = (getattr(message, "content", None) or "").strip()

        parsed = _extract_json(raw_text)
        if parsed is None:
            raise VisionError(
                "OpenAI vision reply was not valid JSON: "
                f"{raw_text[:200]!r}"
            )

        usage = getattr(resp, "usage", None)
        return VisionResult(
            parsed=parsed,
            raw_text=raw_text,
            model=self._model,
            provider_name=self.name,
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0,
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0) if usage else 0,
        )
