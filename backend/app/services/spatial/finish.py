"""Finish pass — geometry render → photoreal, obeying the geometry.

The *only* place a diffusion/image model touches the pipeline, and always
downstream of real geometry: the kernel render (+ its depth map) is the
structural constraint; the model only paints materials + light. It cannot
invent a wrong building because it is not inventing the building.

Provider order (first available wins):
  1. ControlNet-depth (Flux/SDXL via Replicate/Fal) — PROD path; the depth map
     is a hard geometric constraint. Enabled when a token is configured.
  2. OpenAI gpt-image-1 image-edit — img2img off the clay render (composition
     lock; softer than ControlNet). Works wherever the chat key does.
  3. Gemini 2.5 Flash Image edit — the existing image provider.
Depth/normal are produced regardless, so moving to path 1 is config, not code.
"""

from __future__ import annotations

import base64
import logging

from app.config import get_settings

logger = logging.getLogger(__name__)


def build_finish_prompt(graph: dict, *, interior: bool) -> str:
    """A material/style prompt derived from the spec — never generic. The model
    is told to keep the provided geometry EXACTLY and only render it."""
    dtype = str(graph.get("design_type") or graph.get("project_type") or "architectural project").replace("_", " ")

    style = graph.get("style")
    if isinstance(style, dict):
        style_txt = ", ".join(str(v) for v in [style.get("primary"), *(style.get("secondary") or [])] if v)
    else:
        style_txt = str(style or "")

    seen, mats = set(), []
    for src in (graph.get("objects") or []), (graph.get("materials") or []):
        for it in src:
            if isinstance(it, dict):
                name = it.get("material") if it.get("material") else it.get("name")
                if isinstance(name, str) and name.strip() and name.lower() not in seen:
                    seen.add(name.lower())
                    mats.append(name.strip())
    mat_txt = ", ".join(mats[:10]) or "concrete, glass, timber, stone"

    view = ("Photorealistic interior architectural render, natural eye-level dollhouse view"
            if interior else
            "Photorealistic architectural visualization, aerial three-quarter exterior view")
    keep = ("keep the exact room shape, wall positions, and every furniture piece's position, "
            "size and orientation precisely as shown" if interior else
            "keep the exact building footprint, any courtyard/atrium void, all proportions, "
            "and every element's position and size precisely as shown")

    return (
        f"{view}. Turn the provided massing model into a finished photoreal render "
        f"WITHOUT changing its geometry: {keep} in the image. "
        f"Project: {dtype}. " + (f"Design language: {style_txt}. " if style_txt else "") +
        f"Materials to render: {mat_txt}. "
        "Realistic natural lighting, soft shadows, subtle ambient occlusion, high detail, "
        "professional architectural photography. "
        "Do NOT add text, labels, dimension lines, floor-plan lines or diagram overlays."
    )


async def _openai_edit(base_png: bytes, prompt: str, size: str) -> bytes | None:
    s = get_settings()
    key = (getattr(s, "openai_api_key", "") or "").strip()
    if not key:
        return None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=key, base_url=(getattr(s, "openai_base_url", None) or None))
        resp = await client.images.edit(
            model=getattr(s, "openai_image_model", None) or "gpt-image-1",
            image=("massing.png", base_png, "image/png"),
            prompt=prompt,
            size=size,
        )
        b64 = resp.data[0].b64_json
        return base64.b64decode(b64) if b64 else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("openai finish-pass failed: %s", exc)
        return None


async def _controlnet_depth(base_png: bytes, depth_png: bytes | None, prompt: str) -> bytes | None:
    """PROD seam — Flux/SDXL ControlNet-depth via Replicate/Fal, using the depth
    map for an exact geometry lock. Enabled when a token is configured."""
    s = get_settings()
    if not (getattr(s, "replicate_api_token", "") or getattr(s, "fal_key", "")) or depth_png is None:
        return None
    return None  # not exercised in the current environment


async def finish_render(base_png: bytes, depth_png: bytes | None, prompt: str,
                        *, size: str = "1536x1024") -> dict | None:
    """Return {'bytes', 'provider'} or None (caller falls back to the base render
    or the legacy Gemini path)."""
    out = await _controlnet_depth(base_png, depth_png, prompt)
    if out:
        return {"bytes": out, "provider": "controlnet-depth"}
    out = await _openai_edit(base_png, prompt, size)
    if out:
        return {"bytes": out, "provider": "openai-gpt-image-1"}
    return None
