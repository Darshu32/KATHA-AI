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


def build_finish_prompt(graph: dict, *, kind: str = "interior") -> str:
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

    if kind == "product":
        view = ("Photorealistic studio product photograph, the single object centred on a "
                "seamless neutral background, soft studio lighting, three-quarter view. "
                "Show ONLY this one object — no other furniture, no wall art, no plants, no "
                "props, nothing else in the frame")
        keep = ("keep the exact object shape, proportions, and every part's position, size and "
                "orientation precisely as shown, with all parts joined into one solid object")
    elif kind == "interior":
        view = "Photorealistic interior architectural render, natural eye-level dollhouse view"
        keep = ("keep the exact room shape and wall positions precisely as shown, and keep every "
                "furniture block at the same position, footprint and height — but render each block "
                "AS the realistic furniture piece it represents (bed, sofa, armchair, table, wardrobe, "
                "cabinet, kitchen counter, appliance), never leaving it as a plain box or clay volume")
    else:  # exterior
        view = "Photorealistic architectural visualization, aerial three-quarter exterior view"
        keep = ("keep the exact building footprint, any courtyard/atrium void, all proportions, "
                "and every element's position and size precisely as shown")

    return (
        f"{view}. Turn the provided 3D model into a finished photoreal render "
        f"WITHOUT changing its geometry: {keep} in the image. "
        f"Project: {dtype}. " + (f"Design language: {style_txt}. " if style_txt else "") +
        f"Materials to render: {mat_txt}. "
        "Realistic natural lighting, soft shadows, subtle ambient occlusion, high detail, "
        "professional architectural photography. "
        "CRITICAL — treat the provided image as a LOCKED structural template: do NOT add, "
        "remove, relocate, resize, merge or invent ANY element. No extra walls, panels, "
        "glass, dividers, furniture, legs or props that are not already in the model; no "
        "missing ones either. Keep the exact silhouette, part count and every edge; change "
        "ONLY surface material, colour and lighting. "
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


async def _gemini_edit(base_png: bytes, prompt: str, ref_png: bytes | None = None) -> bytes | None:
    """Nano Banana (Gemini 2.5 Flash Image) img2img finish — the clay render is
    the attached reference the model must KEEP; it only paints materials + light.
    Same provider ReRender-style tools use, and KATHA's target image stack.

    When a ``ref_png`` (the kernel DEPTH MAP) is supplied it's attached as a
    SECOND reference and the prompt tells the model to hold the 3D structure to
    it — extra geometry signal to curb img2img drift without a ControlNet."""
    s = get_settings()
    key = (getattr(s, "gemini_api_key", "") or "").strip()
    if not key:
        return None
    model = getattr(s, "gemini_image_model", None) or "gemini-2.5-flash-image"
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={key}")
    parts: list = [
        {"inlineData": {"mimeType": "image/png", "data": base64.b64encode(base_png).decode()}},
    ]
    text = prompt
    if ref_png:
        parts.append({"inlineData": {"mimeType": "image/png", "data": base64.b64encode(ref_png).decode()}})
        text = (prompt + " Two images are provided: the FIRST is the clay 3D model to render; "
                "the SECOND is its exact DEPTH MAP — use it to hold the precise 3D structure, "
                "proportions and part positions. Render only the first; do not depict the depth map.")
    parts.append({"text": text})
    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=90.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        for cand in data.get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData")
                if inline and str(inline.get("mimeType", "")).startswith("image/"):
                    b64 = inline.get("data")
                    return base64.b64decode(b64) if b64 else None
        logger.warning("gemini finish-pass returned no image parts")
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("gemini finish-pass failed: %s", exc)
        return None


async def _controlnet_depth(base_png: bytes, depth_png: bytes | None, prompt: str) -> bytes | None:
    """PROD finish lock — a Flux/SDXL **depth-ControlNet** via Replicate,
    conditioned on the kernel DEPTH MAP for the tightest possible geometry lock
    (a hard constraint, vs the img2img composition-lock of Gemini/OpenAI).

    Active only when BOTH ``replicate_api_token`` and ``controlnet_depth_model``
    are configured; otherwise dormant. Any failure returns None so the caller
    falls back to the img2img providers — this never breaks the finish."""
    s = get_settings()
    token = (getattr(s, "replicate_api_token", "") or "").strip()
    model = (getattr(s, "controlnet_depth_model", "") or "").strip()
    if not token or not model or base_png is None:
        return None

    import asyncio

    import httpx
    # flux-depth-dev extracts the depth structure from the control image, so we
    # hand it the CLAY render (clean, unambiguous kernel geometry) and it locks
    # the output to that depth — it can't add or move geometry the way img2img
    # can. If a depth-NATIVE ControlNet is configured (controlnet_send_depth) and
    # a kernel depth map exists, send that instead — a pre-computed depth is
    # tighter than an extracted one.
    send_depth = bool(getattr(s, "controlnet_send_depth", False)) and depth_png is not None
    control_bytes = depth_png if send_depth else base_png
    control = "data:image/png;base64," + base64.b64encode(control_bytes).decode()
    payload = {
        "prompt": prompt,
        "control_image": control,
        "guidance": float(getattr(s, "controlnet_guidance", 12.0) or 12.0),
        "num_inference_steps": int(getattr(s, "controlnet_steps", 28) or 28),
        "output_format": "png",
    }
    url = f"https://api.replicate.com/v1/models/{model}/predictions"
    auth = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            resp = await client.post(
                url,
                json={"input": payload},
                headers={**auth, "Content-Type": "application/json", "Prefer": "wait"},
            )
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            get_url = (data.get("urls") or {}).get("get")
            # 'Prefer: wait' usually resolves synchronously; poll as a fallback.
            for _ in range(60):
                if status in ("succeeded", "failed", "canceled") or not get_url:
                    break
                await asyncio.sleep(2)
                r = await client.get(get_url, headers=auth)
                data = r.json()
                status = data.get("status")
            if status != "succeeded":
                logger.warning("controlnet-depth: prediction did not succeed (status=%s)", status)
                return None
            img_url = _first_output_url(data.get("output"))
            if not img_url:
                logger.warning("controlnet-depth: no output image in %s", str(data.get("output"))[:120])
                return None
            img = await client.get(img_url)
            img.raise_for_status()
            logger.info("controlnet-depth: finished via %s (control=%s)", model, "depth" if send_depth else "clay")
            return img.content
    except Exception as exc:  # noqa: BLE001 — never break the finish
        logger.warning("controlnet-depth finish failed: %s", exc)
        return None


def _first_output_url(out) -> str | None:
    """Replicate output can be a URL string, a list of URLs, or a dict — normalise
    to the first image URL, or None."""
    if isinstance(out, str):
        return out or None
    if isinstance(out, list) and out:
        first = out[0]
        if isinstance(first, str):
            return first or None
        if isinstance(first, dict):
            return first.get("url") or first.get("image")
        return None
    if isinstance(out, dict):
        return out.get("url") or out.get("image")
    return None


# provider name → (coroutine factory, reported label)
async def _run_provider(name: str, base_png: bytes, prompt: str, size: str,
                        depth_png: bytes | None = None) -> dict | None:
    if name == "gemini":
        out = await _gemini_edit(base_png, prompt, depth_png)
        return {"bytes": out, "provider": "gemini-2.5-flash-image"} if out else None
    if name == "openai":
        out = await _openai_edit(base_png, prompt, size)
        return {"bytes": out, "provider": "openai-gpt-image-1"} if out else None
    return None


async def finish_render(base_png: bytes, depth_png: bytes | None, prompt: str,
                        *, size: str = "1536x1024", provider: str | None = None,
                        geometry_locked_only: bool = False) -> dict | None:
    """Return {'bytes', 'provider'} or None (caller falls back to the base render
    or the legacy Gemini path).

    Provider order: ControlNet-depth (hard geometry lock) when configured, then
    the preferred image provider, then the other as automatic fallback. The
    preference is ``provider`` (explicit, for A/B) or the ``spatial_finish_provider``
    setting ("openai" | "gemini").

    ``geometry_locked_only`` restricts the finish to the ControlNet-depth path —
    the ONLY finish that stays faithful to the model. img2img providers (Gemini,
    gpt-image-1) re-imagine the scene (they move and invent furniture), so a
    render meant to match the plan/drawings must never use them. When True and no
    depth-lock is configured, returns None so the caller serves the exact kernel
    render instead."""
    out = await _controlnet_depth(base_png, depth_png, prompt)
    if out:
        return {"bytes": out, "provider": "controlnet-depth"}
    if geometry_locked_only:
        return None  # no hard lock available → caller keeps the faithful clay render

    pref = (provider or getattr(get_settings(), "spatial_finish_provider", "openai") or "openai").lower()
    order = ["gemini", "openai"] if pref == "gemini" else ["openai", "gemini"]
    for name in order:
        res = await _run_provider(name, base_png, prompt, size, depth_png)
        if res:
            return res
    return None
