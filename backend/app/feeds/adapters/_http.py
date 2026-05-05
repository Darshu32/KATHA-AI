"""Shared HTTP transport helper for live adapters.

Wraps ``httpx.AsyncClient`` with the timeout + retry policy from
``Settings`` so per-adapter code can focus on parsing. Returns
``None`` instead of raising on transport failures — adapters wrap
the call in their own ``FetchOutcome(status='failure')`` envelope.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)


async def fetch_json(
    url: str,
    *,
    settings: Any,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, Any]] = None,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    """GET ``url`` and decode JSON. Returns ``(data, error)``.

    Retries up to ``settings.feed_http_max_retries`` on transient
    network errors (httpx ``HTTPError``) with exponential backoff.
    Non-2xx responses are NOT retried — they're a signal from the
    upstream that the request itself is wrong, not a flake.
    """
    timeout = settings.feed_http_timeout_seconds
    max_attempts = max(1, settings.feed_http_max_retries + 1)

    last_error: Optional[str] = None
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers, params=params)
            if resp.status_code >= 500:
                last_error = f"upstream HTTP {resp.status_code}"
            elif resp.status_code >= 400:
                return None, f"upstream HTTP {resp.status_code}: {resp.text[:200]}"
            else:
                try:
                    return resp.json(), None
                except ValueError as exc:
                    return None, f"json decode: {exc}"
        except httpx.HTTPError as exc:
            last_error = f"transport: {exc}"
            logger.debug("fetch_json attempt %d failed: %s", attempt + 1, exc)
        except Exception as exc:  # noqa: BLE001
            return None, f"unexpected: {exc}"

        if attempt + 1 < max_attempts:
            await asyncio.sleep(0.5 * (2**attempt))

    return None, last_error or "unknown transport error"


async def fetch_text(
    url: str,
    *,
    settings: Any,
    headers: Optional[dict[str, str]] = None,
    params: Optional[dict[str, Any]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """GET ``url`` and return raw text (for HTML scraping)."""
    timeout = settings.feed_http_timeout_seconds
    max_attempts = max(1, settings.feed_http_max_retries + 1)

    last_error: Optional[str] = None
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(url, headers=headers, params=params)
            if resp.status_code >= 500:
                last_error = f"upstream HTTP {resp.status_code}"
            elif resp.status_code >= 400:
                return None, f"upstream HTTP {resp.status_code}"
            else:
                return resp.text, None
        except httpx.HTTPError as exc:
            last_error = f"transport: {exc}"
        except Exception as exc:  # noqa: BLE001
            return None, f"unexpected: {exc}"

        if attempt + 1 < max_attempts:
            await asyncio.sleep(0.5 * (2**attempt))

    return None, last_error or "unknown transport error"
