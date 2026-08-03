"""Vision-grounded object bounding boxes — the edit-loop core.

The click-to-edit hotspots must sit on objects as they were *rendered*, not on
a top-down plan projection of the graph (see ``object_bboxes.py`` for why that
drifts on a perspective render). This service runs Gemini object detection on
the actual rendered image, then maps each detected box back to a design-graph
object id so the edit loop still targets a real object.

Contract mirrors ``object_bboxes.compute_object_bboxes``: a list of
``{id, name, type, x, y, w, h}`` with x/y/w/h normalised to [0, 1] (top-left
origin). Returns ``None`` on any failure/empty result so the caller falls back
to the deterministic plan projection — grounding is an upgrade, never a
dependency.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections import deque
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

# Vision model with native 2D detection. Same API family / key as image gen.
_MODEL = "gemini-2.5-flash"
_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"

# Gemini returns box_2d as [ymin, xmin, ymax, xmax] normalised to 0-1000.
_DETECT_SCHEMA: dict[str, Any] = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "box_2d": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["label", "box_2d"],
    },
}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").strip().lower()).strip("_")


def _detect_prompt(labels: list[str]) -> str:
    return (
        "This is a photorealistic interior render. Detect every clearly visible "
        "instance of these object types: " + ", ".join(labels) + ". "
        'Return JSON {"objects": [{"label": <one of the listed types>, '
        '"box_2d": [ymin, xmin, ymax, xmax]}]} with coordinates normalised '
        "0-1000 from the top-left. Include only objects actually visible; omit "
        "anything you cannot see. No prose."
    )


async def _detect_gemini(image_bytes: bytes, labels: list[str], mime: str) -> list | None:
    """Primary detector — Gemini native 2D detection (prod path)."""
    api_key = (getattr(get_settings(), "gemini_api_key", "") or "").strip()
    if not api_key:
        return None
    payload = {
        "contents": [{"parts": [
            {"inlineData": {"mimeType": mime, "data": base64.b64encode(image_bytes).decode()}},
            {"text": _detect_prompt(labels)},
        ]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {"type": "object", "properties": {"objects": _DETECT_SCHEMA},
                               "required": ["objects"]},
            "temperature": 0.0,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(_ENDPOINT.format(model=_MODEL, key=api_key), json=payload)
            resp.raise_for_status()
            data = resp.json()
        text = "".join(
            p.get("text", "")
            for p in (data.get("candidates") or [{}])[0].get("content", {}).get("parts", [])
        )
        parsed = json.loads(text) if text.strip() else {}
        return parsed.get("objects") if isinstance(parsed, dict) else parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("gemini grounding failed: %s", exc)
        return None


async def _detect_openai(image_bytes: bytes, labels: list[str], mime: str) -> list | None:
    """Fallback detector — OpenAI vision (works wherever the chat key does)."""
    settings = get_settings()
    key = (getattr(settings, "openai_api_key", "") or "").strip()
    if not key:
        return None
    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=key, base_url=(getattr(settings, "openai_base_url", None) or None))
        b64 = base64.b64encode(image_bytes).decode()
        resp = await client.chat.completions.create(
            model=getattr(settings, "openai_vision_model", None) or "gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": _detect_prompt(labels)},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
            ]}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=1500,
        )
        parsed = json.loads(resp.choices[0].message.content or "{}")
        return parsed.get("objects") if isinstance(parsed, dict) else parsed
    except Exception as exc:  # noqa: BLE001
        logger.warning("openai grounding failed: %s", exc)
        return None


async def ground_object_bboxes(
    image_bytes: bytes | None,
    graph: dict,
    *,
    mime: str = "image/png",
) -> list[dict] | None:
    """Detect graph objects in the render and return image-accurate hotspots,
    or ``None`` so the caller falls back to the plan projection. Tries Gemini
    (primary) then OpenAI vision (fallback)."""
    if not image_bytes:
        return None
    objects = [o for o in (graph.get("objects") or []) if isinstance(o, dict)]
    if not objects:
        return None

    labels = sorted({(_norm(o.get("type")) or "object").replace("_", " ") for o in objects})
    detections = await _detect_gemini(image_bytes, labels, mime)
    if not detections:
        detections = await _detect_openai(image_bytes, labels, mime)
    if not isinstance(detections, list) or not detections:
        return None
    return _map_detections(detections, objects)


def _map_detections(detections: list, objects: list[dict]) -> list[dict] | None:
    """Assign each detected box to a graph object of the same type (1:1 by
    detection area, biggest first), reusing the first of a type when the model
    finds more instances than the graph carries."""
    by_type: dict[str, list[dict]] = {}
    for o in objects:
        by_type.setdefault(_norm(o.get("type")), []).append(o)
    queues = {t: deque(objs) for t, objs in by_type.items()}

    def _area(det: Any) -> float:
        b = det.get("box_2d") if isinstance(det, dict) else None
        if not (isinstance(b, list) and len(b) == 4):
            return 0.0
        return max(0, b[2] - b[0]) * max(0, b[3] - b[1])

    out: list[dict] = []
    for i, det in enumerate(sorted(detections, key=_area, reverse=True)):
        if not isinstance(det, dict):
            continue
        b = det.get("box_2d")
        if not (isinstance(b, list) and len(b) == 4):
            continue
        ymin, xmin, ymax, xmax = (float(v) for v in b)
        x = max(0.0, min(1.0, xmin / 1000.0))
        y = max(0.0, min(1.0, ymin / 1000.0))
        w = max(0.0, min(1.0 - x, (xmax - xmin) / 1000.0))  # keep the box in-frame
        h = max(0.0, min(1.0 - y, (ymax - ymin) / 1000.0))
        if w <= 0.005 or h <= 0.005:
            continue

        t = _norm(det.get("label"))
        gt = t if t in queues else next((k for k in queues if k and (k in t or t in k)), None)
        obj = None
        if gt and queues[gt]:
            obj = queues[gt].popleft()
        elif gt and by_type.get(gt):
            obj = by_type[gt][-1]  # more detections than objects → reuse last of type

        if obj is not None:
            oid = obj.get("id") or f"obj-{i}"
            name = obj.get("name") or (obj.get("type") or "object")
            otype = obj.get("type") or t
        else:
            # Detected something not in the graph — keep it as a labelled
            # hotspot (not editable, but at least accurate to the image).
            oid = f"det-{i}"
            name = str(det.get("label") or "object")
            otype = t or "object"

        out.append({
            "id": oid,
            "name": name,
            "type": otype,
            "x": round(x, 4),
            "y": round(y, 4),
            "w": round(w, 4),
            "h": round(h, 4),
            "grounded": True,
        })
    return out or None
