"""Chat routes — SSE streaming + media endpoints for Architecture Knowledge Intelligence."""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.services.chat_engine import stream_chat_response
from app.services.image_service import (
    generate_image,
    search_youtube,
    search_research_papers,
    generate_video,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])


# ── Request Models ──────────────────────────────────────────────────────────


class ChatMessageInput(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=10000)
    conversation_history: list[ChatMessageInput] = Field(default_factory=list)
    mode: str | None = Field(
        default=None,
        description="Response mode: 'quick', 'deep', or null for auto-detect",
    )


class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)


class YouTubeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=3, ge=1, le=10)
    duration: str = Field(default="any", description="short | medium | long | any")


class PaperSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=3, ge=1, le=10)


class VideoGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=1000)


# ── Media Endpoints ─────────────────────────────────────────────────────────


@router.post("/generate-image")
async def generate_image_endpoint(body: ImageGenerateRequest):
    """Generate an AI architecture image using Nano Banana (Gemini)."""
    image = await generate_image(body.prompt)
    return {"image": image}


@router.post("/search-youtube")
async def search_youtube_endpoint(body: YouTubeSearchRequest):
    """Search YouTube for architecture videos."""
    videos = await search_youtube(body.query, body.max_results, body.duration)
    return {"videos": videos}


@router.post("/search-papers")
async def search_papers_endpoint(body: PaperSearchRequest):
    """Search Semantic Scholar for architecture research papers."""
    papers = await search_research_papers(body.query, body.max_results)
    return {"papers": papers}


@router.post("/generate-video")
async def generate_video_endpoint(body: VideoGenerateRequest):
    """Generate a short architecture video using Sora (when available)."""
    video = await generate_video(body.prompt)
    return {"video": video}


# ── Chat Streaming ──────────────────────────────────────────────────────────


@router.post("/stream")
async def chat_stream(body: ChatRequest, request: Request):
    """Stream an AI-powered architecture knowledge response via SSE.

    SSE event types:
      - token:  {"type": "token", "content": "..."}
      - done:   {"type": "done", "content", "suggestions", "image_prompt", "video_query", "youtube_query", "research_query", "reference_links", "mode"}
      - error:  {"type": "error", "content": "..."}
    """
    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]

    async def event_generator():
        async for event in stream_chat_response(
            user_message=body.message,
            conversation_history=history,
            mode=body.mode,
        ):
            if await request.is_disconnected():
                logger.info("Client disconnected during chat stream")
                break
            yield event

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
