"""Media service — AI image generation (Nano Banana), YouTube search, and research papers."""

import asyncio
import base64
import logging
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


def _settings():
    return get_settings()


# ── AI Image Generation (Google Nano Banana / Gemini) ───────────────────────


async def generate_image(prompt: str) -> dict[str, Any] | None:
    """Generate an architecture image using Google Nano Banana (Gemini Image API).

    Uses the Gemini API with image generation capabilities.
    Returns {"url": str, "title": str, "source": "nano-banana", "type": "ai-image"} or None.
    """
    s = _settings()
    api_key = s.gemini_api_key
    if not api_key or not api_key.strip():
        logger.info("GEMINI_API_KEY not configured for image generation")
        return None

    arch_prompt = (
        f"Generate a professional architectural visualization: {prompt}. "
        "Photorealistic, high detail, clean composition, studio quality. "
        "Architecture photography style with natural lighting. "
        "No text, no watermarks, no labels."
    )

    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent?key={api_key}"

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": arch_prompt}
                ]
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT", "IMAGE"],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # Extract image from response
        candidates = data.get("candidates", [])
        if not candidates:
            logger.warning("Nano Banana returned no candidates")
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        for part in parts:
            inline_data = part.get("inlineData")
            if inline_data and inline_data.get("mimeType", "").startswith("image/"):
                # Convert base64 image to data URL for frontend display
                mime = inline_data["mimeType"]
                b64_data = inline_data["data"]
                data_url = f"data:{mime};base64,{b64_data}"

                return {
                    "url": data_url,
                    "thumbnail": data_url,
                    "title": prompt,
                    "source": "nano-banana",
                    "type": "ai-image",
                }

        logger.warning("Nano Banana response contained no image parts")
        return None

    except Exception as exc:
        logger.error("Nano Banana image generation failed: %s", exc)
        return None


# ── YouTube Video Search ────────────────────────────────────────────────────


async def search_youtube(
    query: str,
    max_results: int = 3,
    duration: str = "any",
) -> list[dict[str, str]]:
    """Search YouTube for architecture-related videos.

    Args:
        query: Search query string
        max_results: Number of results (1-10)
        duration: "short" (< 4 min), "medium" (4-20 min), "long" (> 20 min), "any"

    Returns list of {"video_id", "title", "thumbnail", "channel", "url", "type": "youtube"}.
    """
    s = _settings()
    api_key = s.youtube_api_key
    if not api_key or not api_key.strip():
        logger.info("YOUTUBE_API_KEY not configured")
        return []

    url = "https://www.googleapis.com/youtube/v3/search"
    params: dict[str, Any] = {
        "part": "snippet",
        "type": "video",
        "q": f"{query} architecture",
        "maxResults": max_results,
        "key": api_key,
        "relevanceLanguage": "en",
        "safeSearch": "strict",
        "order": "relevance",
    }

    # Add duration filter if specified
    if duration in ("short", "medium", "long"):
        params["videoDuration"] = duration

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for item in data.get("items", [])[:max_results]:
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId", "")
            if not video_id:
                continue

            thumbnails = snippet.get("thumbnails", {})
            thumbnail = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url", "")
            )

            results.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "thumbnail": thumbnail,
                "channel": snippet.get("channelTitle", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "source": "youtube",
                "type": "youtube",
            })

        return results

    except Exception as exc:
        logger.error("YouTube search failed: %s", exc)
        return []


# ── Research Paper Search (Semantic Scholar) ────────────────────────────────


async def search_research_papers(
    query: str,
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Search Semantic Scholar for architecture research papers.

    Free API, no key required.
    Returns list of {"title", "url", "year", "authors", "citations", "type": "paper"}.
    """
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": query,
        "limit": max_results,
        "fields": "title,url,year,authors,citationCount",
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results = []
        for paper in data.get("data", [])[:max_results]:
            authors = paper.get("authors", [])
            author_names = ", ".join(
                a.get("name", "") for a in authors[:3]
            )
            if len(authors) > 3:
                author_names += " et al."

            results.append({
                "title": paper.get("title", ""),
                "url": paper.get("url", ""),
                "year": paper.get("year"),
                "authors": author_names,
                "citations": paper.get("citationCount", 0),
                "type": "paper",
            })

        return results

    except Exception as exc:
        logger.error("Semantic Scholar search failed: %s", exc)
        return []


# ── Video Generation (Sora — future) ───────────────────────────────────────


async def generate_video(prompt: str) -> dict[str, Any] | None:
    """Generate a short architecture video using OpenAI Sora.

    Behind the `sora_enabled` feature flag. Returns None when disabled or on failure.
    """
    s = _settings()
    if not s.sora_enabled:
        return None

    # Sora API integration — placeholder for when the API is publicly available
    # When ready, use the OpenAI client with the Sora endpoint
    logger.info("Sora video generation is not yet implemented")
    return None


# ── Combined Media Fetchers ─────────────────────────────────────────────────


async def fetch_quick_mode_media(
    image_prompt: str | None,
    video_query: str | None,
) -> dict[str, Any]:
    """Fetch all media for Quick Mode concurrently.

    Returns {"image": dict|None, "video": dict|None}.
    """
    tasks = {}

    if image_prompt:
        tasks["image"] = generate_image(image_prompt)

    if video_query:
        # Try Sora first, fall back to YouTube short clip
        tasks["video"] = _get_video_or_youtube(video_query)

    if not tasks:
        return {"image": None, "video": None}

    keys = list(tasks.keys())
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    media: dict[str, Any] = {"image": None, "video": None}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            logger.error("Quick mode media fetch failed for %s: %s", key, result)
        else:
            media[key] = result

    return media


async def _get_video_or_youtube(query: str) -> dict[str, Any] | None:
    """Try Sora video generation, fall back to YouTube short clip."""
    video = await generate_video(query)
    if video:
        return video

    # Fall back to YouTube short clip
    results = await search_youtube(query, max_results=1, duration="short")
    return results[0] if results else None


async def fetch_deep_mode_media(
    image_prompt: str | None,
    youtube_query: str | None,
    research_query: str | None,
) -> dict[str, Any]:
    """Fetch all media for Deep Mode concurrently.

    Returns {"image": dict|None, "youtube_links": list, "research_papers": list}.
    """
    tasks = {}

    if image_prompt:
        tasks["image"] = generate_image(image_prompt)
    if youtube_query:
        tasks["youtube_links"] = search_youtube(youtube_query, max_results=3, duration="medium")
    if research_query:
        tasks["research_papers"] = search_research_papers(research_query, max_results=3)

    if not tasks:
        return {"image": None, "youtube_links": [], "research_papers": []}

    keys = list(tasks.keys())
    results = await asyncio.gather(*tasks.values(), return_exceptions=True)

    media: dict[str, Any] = {"image": None, "youtube_links": [], "research_papers": []}
    for key, result in zip(keys, results):
        if isinstance(result, Exception):
            logger.error("Deep mode media fetch failed for %s: %s", key, result)
        else:
            media[key] = result

    return media
