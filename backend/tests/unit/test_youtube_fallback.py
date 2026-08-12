"""Deep mode's video link must never be silently blank.

When the YouTube Data API is unavailable (no key / quota / error / no hits),
``search_youtube`` returns a search-URL fallback so the note always carries a
real, on-topic "Watch on YouTube" link.
"""
from __future__ import annotations

import pytest

import app.services.image_service as mod
from app.services.image_service import _youtube_search_fallback, search_youtube


def test_fallback_is_an_on_topic_search_link():
    out = _youtube_search_fallback("how HVAC works")
    assert len(out) == 1
    item = out[0]
    assert item["type"] == "youtube"
    assert item["url"].startswith("https://www.youtube.com/results?search_query=")
    assert "hvac" in item["url"].lower()
    assert item["thumbnail"] == ""      # no single video → callers show a play glyph


@pytest.mark.asyncio
async def test_search_youtube_never_returns_empty_without_a_key(monkeypatch):
    class _NoKeySettings:
        youtube_api_key = ""

    monkeypatch.setattr(mod, "_settings", lambda: _NoKeySettings())
    out = await search_youtube("passive cooling strategies")
    assert len(out) >= 1
    assert out[0]["url"].startswith("https://www.youtube.com/")
