"""Concept stage for the design orchestration pipeline."""

from __future__ import annotations

import json
import logging
import re
from time import perf_counter

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

_client: AsyncOpenAI | None = None

REQUIRED_FIELDS = (
    "concept_summary",
    "design_intent",
    "color_strategy",
    "material_strategy",
    "lighting_strategy",
    "furniture_strategy",
    "spatial_strategy",
    "style_keywords",
    "negative_keywords",
)

CONCEPT_JSON_SCHEMA = {
    "name": "architectural_concept",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "concept_summary": {"type": "string"},
            "design_intent": {"type": "string"},
            "color_strategy": {"type": "string"},
            "material_strategy": {"type": "string"},
            "lighting_strategy": {"type": "string"},
            "furniture_strategy": {"type": "string"},
            "spatial_strategy": {"type": "string"},
            "style_keywords": {"type": "array", "items": {"type": "string"}},
            "negative_keywords": {"type": "array", "items": {"type": "string"}},
        },
        "required": list(REQUIRED_FIELDS),
        "additionalProperties": False,
    },
}

SYSTEM_PROMPT = """
You are a senior architect and interior designer creating a buildable design concept.
Return only valid JSON that matches the requested schema.

Rules:
- Be specific, not generic.
- Respect the theme, dos, donts, and spatial preferences.
- Keep the concept realistic and suitable for downstream layout, drawing, rendering, and costing.
- Mention circulation, furniture behavior, and architectural intent where useful.
- Negative keywords must describe styles, materials, moods, or mistakes to avoid.
- Keep concept_summary concise at no more than 2 sentences.
- Keep design_intent concise at no more than 6 sentences.
""".strip()


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


def _has_openai_config() -> bool:
    return bool(settings.openai_api_key and settings.openai_api_key.strip())


def build_concept_prompt(input_data: dict, theme_config: dict) -> str:
    dimensions = input_data.get("dimensions", {})
    budget = input_data.get("budget")
    budget_line = budget if budget is not None else "unspecified"

    prompt = f"""
Design a {input_data.get("room_type", "space")} using the {theme_config.get("style", "modern")} style.

User Input:
- Room type: {input_data.get("room_type", "space")}
- Dimensions: {json.dumps(dimensions)}
- Requirements: {input_data.get("requirements", "")}
- Budget: {budget_line}

Theme Rules:
- Style intensity: {theme_config.get("style_intensity", "medium")}
- Colors: {", ".join(theme_config.get("colors", []))}
- Color roles: {json.dumps(theme_config.get("color_roles", {}))}
- Materials: {", ".join(theme_config.get("materials", []))}
- Lighting: {theme_config.get("lighting", "")}
- Furniture style: {theme_config.get("furniture_style", "")}
- Textures: {", ".join(theme_config.get("textures", []))}
- Decor: {", ".join(theme_config.get("decor", []))}
- DO: {"; ".join(theme_config.get("dos", []))}
- DO NOT: {"; ".join(theme_config.get("donts", []))}
- Spatial preferences: {json.dumps(theme_config.get("spatial_preferences", {}))}

Provide:
- concept_summary
- design_intent
- color_strategy
- material_strategy
- lighting_strategy
- furniture_strategy
- spatial_strategy
- style_keywords
- negative_keywords
""".strip()
    _log_event(
        logging.INFO,
        "prompt_built",
        room_type=input_data.get("room_type"),
        style=theme_config.get("style"),
        style_intensity=theme_config.get("style_intensity"),
    )
    return prompt


async def process(input_data: dict, theme_config: dict) -> dict:
    """
    Generate a structured architectural concept using the intake brief and theme rules.
    Falls back to a deterministic concept when the LLM is unavailable or returns invalid output.
    """
    debug_enabled = bool(input_data.get("debug"))
    _log_event(
        logging.INFO,
        "concept_generation_started",
        room_type=input_data.get("room_type"),
        style=theme_config.get("style"),
        style_intensity=theme_config.get("style_intensity"),
        debug=debug_enabled,
    )

    prompt = build_concept_prompt(input_data, theme_config)

    if not _has_openai_config():
        _log_event(
            logging.WARNING,
            "fallback_used",
            style=theme_config.get("style"),
            reason="openai_api_key_missing",
        )
        return _finalize_response(
            base_concept=_build_fallback_concept(input_data, theme_config),
            input_data=input_data,
            theme_config=theme_config,
            confidence=0.25,
            debug_enabled=debug_enabled,
            debug_data={
                "prompt_used": prompt,
                "model": settings.openai_model,
                "tokens_used": 0,
                "latency_ms": 0,
            },
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            source="fallback",
        )

    last_error: Exception | None = None

    for attempt in range(1, 3):
        try:
            llm_result = await _generate_concept_via_llm(prompt)
            normalized = _normalize_concept_output(
                llm_result["content"],
                input_data=input_data,
                theme_config=theme_config,
                source="llm",
            )
            _log_event(
                logging.INFO,
                "concept_generated",
                style=theme_config.get("style"),
                attempt=attempt,
                source="llm",
                confidence=normalized["confidence"],
            )
            return _finalize_response(
                base_concept=normalized,
                input_data=input_data,
                theme_config=theme_config,
                confidence=normalized["confidence"],
                debug_enabled=debug_enabled,
                debug_data={
                    "prompt_used": prompt,
                    "model": settings.openai_model,
                    "tokens_used": llm_result["usage"]["total_tokens"],
                    "latency_ms": llm_result["latency_ms"],
                },
                usage=llm_result["usage"],
                source="llm",
            )
        except Exception as exc:
            last_error = exc
            _log_event(
                logging.ERROR,
                "concept_failed",
                style=theme_config.get("style"),
                attempt=attempt,
                error=str(exc),
            )

    _log_event(
        logging.WARNING,
        "fallback_used",
        style=theme_config.get("style"),
        reason=str(last_error) if last_error else "unknown",
    )
    return _finalize_response(
        base_concept=_build_fallback_concept(input_data, theme_config),
        input_data=input_data,
        theme_config=theme_config,
        confidence=0.35,
        debug_enabled=debug_enabled,
        debug_data={
            "prompt_used": prompt,
            "model": settings.openai_model,
            "tokens_used": 0,
            "latency_ms": 0,
        },
        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        source="fallback",
    )


async def _generate_concept_via_llm(prompt: str) -> dict:
    client = _get_client()
    started_at = perf_counter()
    _log_event(logging.INFO, "llm_called", model=settings.openai_model)
    response = await client.chat.completions.create(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": CONCEPT_JSON_SCHEMA,
        },
        temperature=0.3,
        max_tokens=1400,
    )
    latency_ms = int((perf_counter() - started_at) * 1000)
    usage = {
        "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
        "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
        "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
    }
    _log_event(
        logging.INFO,
        "llm_response_received",
        model=settings.openai_model,
        latency_ms=latency_ms,
        total_tokens=usage["total_tokens"],
    )
    content = response.choices[0].message.content
    return {"content": json.loads(content), "usage": usage, "latency_ms": latency_ms}


def _normalize_concept_output(
    concept: dict,
    *,
    input_data: dict,
    theme_config: dict,
    source: str,
) -> dict:
    fixes_applied = 0
    normalized: dict = {}

    for field_name in REQUIRED_FIELDS:
        raw_value = concept.get(field_name)
        if raw_value is None:
            raw_value = _safe_default(field_name, input_data, theme_config)
            fixes_applied += 1

        if field_name in {"style_keywords", "negative_keywords"}:
            normalized[field_name] = _sanitize_list(raw_value)
            if not normalized[field_name]:
                normalized[field_name] = _safe_default(field_name, input_data, theme_config)
                fixes_applied += 1
        else:
            sanitized = _sanitize_text(raw_value)
            if not sanitized:
                sanitized = _safe_default(field_name, input_data, theme_config)
                fixes_applied += 1
            normalized[field_name] = sanitized

    normalized["concept_summary"] = _trim_sentences(normalized["concept_summary"], max_sentences=2)
    normalized["design_intent"] = _trim_sentences(normalized["design_intent"], max_sentences=6)

    tags = _extract_tags(normalized, theme_config)
    confidence = _calculate_confidence(source=source, fixes_applied=fixes_applied)

    normalized.update(
        {
            "tags": tags,
            "confidence": confidence,
            "summary": normalized["concept_summary"],
            "dimensions": input_data["dimensions"],
            "theme_reference": theme_config,
        }
    )

    _log_event(
        logging.INFO,
        "response_validated",
        style=theme_config.get("style"),
        confidence=confidence,
        fixes_applied=fixes_applied,
    )
    return normalized


def _build_fallback_concept(input_data: dict, theme_config: dict) -> dict:
    room_type = str(input_data.get("room_type", "space")).replace("_", " ")
    dimensions = input_data.get("dimensions", {})
    style = theme_config.get("style", "modern")
    colors = ", ".join(theme_config.get("colors", []))
    materials = ", ".join(theme_config.get("materials", []))
    dos = "; ".join(theme_config.get("dos", []))
    donts = "; ".join(theme_config.get("donts", []))
    spatial_preferences = theme_config.get("spatial_preferences", {})
    mood_tags = [style, theme_config.get("lighting", "balanced lighting"), theme_config.get("furniture_style", "")]

    concept = {
        "concept_summary": (
            f"A {style} {room_type} concept built around {input_data.get('requirements', '').strip()} "
            f"while preserving a realistic, buildable interior expression."
        ),
        "design_intent": (
            f"Organize the {room_type} around the given footprint {dimensions} and the user's priorities. "
            f"Use the theme rules to guide layout, atmosphere, and detailing. "
            f"Prioritize these directives: {dos}. "
            f"Respect these exclusions: {donts}. "
            f"Let spatial decisions reflect {spatial_preferences}."
        ),
        "color_strategy": (
            f"Use {colors} according to the defined color roles so the palette stays consistent with the {style} theme."
        ),
        "material_strategy": (
            f"Prioritize {materials} to express the theme authentically while keeping finishes practical and buildable."
        ),
        "lighting_strategy": (
            f"Use {theme_config.get('lighting', 'balanced lighting')} and support natural light wherever possible."
        ),
        "furniture_strategy": (
            f"Adopt a {theme_config.get('furniture_style', 'balanced')} furniture language that supports circulation and function."
        ),
        "spatial_strategy": (
            f"Follow spatial preferences {spatial_preferences}, keep circulation legible, and ensure the room feels intentionally zoned."
        ),
        "style_keywords": _sanitize_list(
            [
                theme_config.get("style", "modern"),
                *theme_config.get("materials", [])[:2],
                *theme_config.get("textures", [])[:2],
            ]
        ),
        "negative_keywords": _sanitize_list(theme_config.get("donts", [])) or ["generic", "impractical"],
    }
    concept["tags"] = {
        "style": _sanitize_list([theme_config.get("style", "modern"), theme_config.get("style_intensity", "medium")]),
        "materials": _sanitize_list(theme_config.get("materials", [])[:3]),
        "mood": _sanitize_list(mood_tags[:3]),
        "lighting": _sanitize_list([theme_config.get("lighting", "balanced lighting")]),
    }
    return concept


def _finalize_response(
    *,
    base_concept: dict,
    input_data: dict,
    theme_config: dict,
    confidence: float,
    debug_enabled: bool,
    debug_data: dict,
    usage: dict,
    source: str,
) -> dict:
    concept_record = {
        "concept_summary": base_concept["concept_summary"],
        "design_intent": base_concept["design_intent"],
        "color_strategy": base_concept["color_strategy"],
        "material_strategy": base_concept["material_strategy"],
        "lighting_strategy": base_concept["lighting_strategy"],
        "furniture_strategy": base_concept["furniture_strategy"],
        "spatial_strategy": base_concept["spatial_strategy"],
        "style_keywords": list(base_concept["style_keywords"]),
        "negative_keywords": list(base_concept["negative_keywords"]),
        "tags": dict(base_concept["tags"]),
        "confidence": confidence,
    }

    response = {
        **concept_record,
        "summary": base_concept["concept_summary"],
        "dimensions": input_data["dimensions"],
        "theme_reference": theme_config,
        "concepts": [concept_record],
        "usage": usage,
    }

    if debug_enabled:
        response["debug"] = {
            "prompt_used": debug_data["prompt_used"],
            "model": debug_data["model"],
            "tokens_used": debug_data["tokens_used"],
            "latency_ms": debug_data["latency_ms"],
        }

    return response


def _extract_tags(concept: dict, theme_config: dict) -> dict:
    text_blob = " ".join(
        [
            concept["concept_summary"],
            concept["design_intent"],
            concept["lighting_strategy"],
            concept["material_strategy"],
        ]
    ).lower()

    style_tags = _sanitize_list(
        [
            theme_config.get("style", "modern"),
            theme_config.get("style_intensity", "medium"),
            *concept.get("style_keywords", [])[:2],
        ]
    )
    material_tags = _sanitize_list(
        [material for material in theme_config.get("materials", []) if material.lower() in text_blob]
        or theme_config.get("materials", [])[:3]
    )
    mood_tags = _sanitize_list(
        _keyword_hits(
            text_blob,
            ["calm", "airy", "warm", "premium", "layered", "cozy", "functional", "bright", "refined"],
        )
        or [theme_config.get("furniture_style", ""), theme_config.get("lighting", "")]
    )
    lighting_tags = _sanitize_list(
        _keyword_hits(
            text_blob,
            ["natural light", "ambient", "accent", "diffused", "dramatic", "warm", "soft"],
        )
        or [theme_config.get("lighting", "balanced lighting")]
    )

    return {
        "style": style_tags,
        "materials": material_tags,
        "mood": mood_tags[:3],
        "lighting": lighting_tags[:3],
    }


def _keyword_hits(text: str, candidates: list[str]) -> list[str]:
    return [candidate for candidate in candidates if candidate.lower() in text]


def _calculate_confidence(*, source: str, fixes_applied: int) -> float:
    if source == "fallback":
        return 0.35
    if fixes_applied == 0:
        return 0.95
    if fixes_applied <= 2:
        return 0.75
    return 0.6


def _safe_default(field_name: str, input_data: dict, theme_config: dict):
    room_type = str(input_data.get("room_type", "space")).replace("_", " ")
    style = theme_config.get("style", "modern")
    defaults = {
        "concept_summary": f"A {style} {room_type} concept shaped around the provided requirements.",
        "design_intent": f"Create a buildable {room_type} that aligns with the {style} theme and user requirements.",
        "color_strategy": f"Use the {style} palette from the theme rules in a balanced architectural way.",
        "material_strategy": f"Use {', '.join(theme_config.get('materials', []))} to express the chosen style.",
        "lighting_strategy": f"Use {theme_config.get('lighting', 'balanced lighting')} throughout the space.",
        "furniture_strategy": f"Apply a {theme_config.get('furniture_style', 'balanced')} furniture direction.",
        "spatial_strategy": "Preserve clear circulation and align the layout with the spatial preferences.",
        "style_keywords": _sanitize_list([theme_config.get("style", "modern"), *theme_config.get("materials", [])[:2]]),
        "negative_keywords": _sanitize_list(theme_config.get("donts", [])) or ["generic", "impractical"],
    }
    return defaults[field_name]


def _sanitize_text(value) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _sanitize_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _sanitize_text(item)
        lowered = text.lower()
        if text and lowered not in seen:
            cleaned.append(text)
            seen.add(lowered)
    return cleaned


def _trim_sentences(text: str, *, max_sentences: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", _sanitize_text(text))
    sentences = [sentence for sentence in sentences if sentence]
    if not sentences:
        return ""
    return " ".join(sentences[:max_sentences]).strip()


def _log_event(level: int, event: str, **fields) -> None:
    logger.log(level, event, extra={"event": event, **fields})
