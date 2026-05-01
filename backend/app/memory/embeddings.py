"""Embeddings — OpenAI text-embedding-3-small wrapper + test stub.

Why an :class:`Embedder` ABC
---------------------------
Tests (and dev environments without an OPENAI_API_KEY) need to be
able to inject a deterministic embedder so the indexer + retriever
exercise without burning real API calls. The production code path
uses :class:`OpenAIEmbedder`; tests use :class:`StubEmbedder`.

Both produce 1536-dim float lists (matching ``text-embedding-3-small``)
so the schema doesn't change between modes.

Cost guardrails
---------------
- One batch call per :func:`embed_many` invocation (OpenAI accepts
  up to 2048 inputs per request).
- Per-call timeout of 30 s.
- ``EmbeddingError`` on any failure — callers decide whether to
  retry, fall back, or surface to the user.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
from abc import ABC, abstractmethod
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────


class EmbeddingError(RuntimeError):
    """Raised when the embedder cannot return vectors for the inputs."""


# ─────────────────────────────────────────────────────────────────────
# Abstract base
# ─────────────────────────────────────────────────────────────────────


class Embedder(ABC):
    """Async embedding provider.

    Implementations promise:

    - The output length matches the input length, in order.
    - Every output vector has exactly ``self.dim`` floats.
    - Empty input list → empty output list (no API call).
    - Any failure raises :class:`EmbeddingError` — never silently
      returns empty / wrong-shaped vectors.
    """

    name: str = "abstract"
    dim: int = 1536

    @abstractmethod
    async def embed_many(self, inputs: list[str]) -> list[list[float]]:
        """Embed a batch of strings. Must preserve input order."""
        ...

    async def embed_one(self, text: str) -> list[float]:
        """Convenience: embed a single string."""
        result = await self.embed_many([text])
        if not result:
            raise EmbeddingError("Embedder returned no vectors for one input")
        return result[0]


# ─────────────────────────────────────────────────────────────────────
# OpenAI
# ─────────────────────────────────────────────────────────────────────


class OpenAIEmbedder(Embedder):
    """Live OpenAI embedder for ``text-embedding-3-small``."""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        model: str = "text-embedding-3-small",
        dim: int = 1536,
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key.strip():
            raise EmbeddingError(
                "OpenAIEmbedder requires an api_key — set OPENAI_API_KEY."
            )
        self.dim = dim
        self.model = model
        self._timeout = timeout_seconds
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def embed_many(self, inputs: list[str]) -> list[list[float]]:
        if not inputs:
            return []
        try:
            resp = await asyncio.wait_for(
                self._client.embeddings.create(
                    model=self.model,
                    input=inputs,
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError as exc:
            raise EmbeddingError(
                f"OpenAI embedding call timed out after {self._timeout}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(f"OpenAI embedding call failed: {exc}") from exc

        # Defensive: we trust OpenAI to return outputs in input order
        # (the API guarantees it via the ``index`` field), but check
        # the length so a shape mismatch is loud, not silent.
        out = [item.embedding for item in resp.data]
        if len(out) != len(inputs):
            raise EmbeddingError(
                f"OpenAI returned {len(out)} vectors for {len(inputs)} inputs"
            )
        for v in out:
            if len(v) != self.dim:
                raise EmbeddingError(
                    f"OpenAI returned a {len(v)}-dim vector; expected {self.dim}"
                )
        return out


# ─────────────────────────────────────────────────────────────────────
# Stub (deterministic, no network)
# ─────────────────────────────────────────────────────────────────────


class StubEmbedder(Embedder):
    """Deterministic embedder for tests + dev without an OpenAI key.

    Hashes the input into a 1536-dim vector. Same input → same vector,
    so ``cosine_similarity(embed("kitchen"), embed("kitchen")) == 1.0``.
    Different inputs land at different points but with no semantic
    relationship — *don't use this in production*.

    The vectors are L2-normalised so cosine similarity in tests behaves
    sensibly (range -1..1).
    """

    name = "stub"

    def __init__(self, dim: int = 1536) -> None:
        self.dim = dim

    async def embed_many(self, inputs: list[str]) -> list[list[float]]:
        return [self._embed_one(s) for s in inputs]

    def _embed_one(self, text: str) -> list[float]:
        # Hash the text into a seed, expand into ``dim`` deterministic
        # floats in [-1, 1], then L2-normalise.
        seed = int.from_bytes(
            hashlib.sha256(text.encode("utf-8", errors="replace")).digest()[:8],
            "big",
        )
        out: list[float] = []
        # LCG for reproducibility — we don't need cryptographic quality
        # here, just a stable mapping from input → vector.
        state = seed if seed != 0 else 1
        for _ in range(self.dim):
            state = (state * 1103515245 + 12345) & 0x7FFFFFFF
            out.append(((state / 0x7FFFFFFF) * 2.0) - 1.0)
        # L2-normalise so cosine_similarity ≡ dot product.
        norm = math.sqrt(sum(x * x for x in out)) or 1.0
        return [x / norm for x in out]


# ─────────────────────────────────────────────────────────────────────
# Factory
# ─────────────────────────────────────────────────────────────────────


def get_embedder() -> Embedder:
    """Return the configured embedder.

    - When ``OPENAI_API_KEY`` is set, returns :class:`OpenAIEmbedder`.
    - Otherwise returns :class:`StubEmbedder` and logs a warning.

    Tests usually override this by passing an explicit embedder to
    the indexer / retriever rather than relying on env state.
    """
    settings = get_settings()
    if settings.has_openai_key:
        return OpenAIEmbedder(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            model=settings.openai_embedding_model,
        )
    log.warning(
        "OPENAI_API_KEY not configured — falling back to StubEmbedder. "
        "Project memory will work but won't have semantic similarity."
    )
    return StubEmbedder()
