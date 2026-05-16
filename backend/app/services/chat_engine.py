"""Chat engine — streams OpenAI responses with the KATHA Architecture Intelligence persona."""

import json
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


def _get_settings():
    return get_settings()


def _get_client() -> AsyncOpenAI:
    """Create a fresh client each time to avoid stale config after .env changes."""
    s = _get_settings()
    return AsyncOpenAI(
        api_key=s.openai_api_key,
        base_url=s.openai_base_url,
    )


# ── Response Metadata ──────────────────────────────────────────────────────


@dataclass
class ResponseMetadata:
    suggestions: list[str] = field(default_factory=list)
    image_prompt: str | None = None
    video_query: str | None = None        # Quick mode — YouTube search for short clip
    youtube_query: str | None = None      # Deep mode — YouTube search for tutorials
    research_query: str | None = None     # Deep mode — Semantic Scholar search
    reference_links: list[dict] = field(default_factory=list)  # Deep mode — AI-provided links
    # Deep mode — BRD §1A 5-section design brief captured from the conversation.
    # Present only when the user is briefing a project (not asking a knowledge Q).
    brief: dict | None = None
    brief_status: dict | None = None      # {section_name: "pending"|"partial"|"confirmed"}
    brief_missing: list[str] = field(default_factory=list)  # dotted paths still pending


# ── System Prompts ──────────────────────────────────────────────────────────

QUICK_MODE_SYSTEM_PROMPT = """You are KATHA AI — an Architecture Knowledge Intelligence System.

You serve architects, architecture students, interior designers, civil planning learners, visualization artists, construction consultants, design studios, and real estate concept teams.

## RESPONSE RULES — QUICK MODE

You are in QUICK MODE. Follow these rules strictly:

1. **Be concise** — answer in 3-5 lines maximum. No long explanations.
2. **Be direct** — lead with the answer, not background context.
3. **Use precise terminology** but keep it accessible.
4. **Include key numbers** — dimensions, ratios, standards, costs when relevant.
5. **End with a suggestion** — always suggest what the user should do next (generate a plan, explore deeper, see examples).

Format: Use bold for key terms. Use bullet points only if listing 3+ items. Never use headers in quick mode.

You are an expert across: structural engineering, Vastu Shastra, interior design, facade systems, MEP services, sustainability (LEED/GRIHA), building codes (NBC/IS), climatology, materials science, construction documentation, cost estimation, and architectural theory.

When discussing dimensions, use both metric and imperial. Reference Indian and international standards where relevant.

IMPORTANT: At the end of your response, output a JSON block on a new line in this exact format:
```json
{"suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"], "video_query": "YouTube search query for a short architecture video about this topic, e.g. 'cantilever balcony construction detail animation'"}
```
Rules for the JSON:
- **suggestions**: 2-3 natural follow-up actions the user might want
- **video_query**: A YouTube search query to find a short (< 4 min) video clip showing this concept in practice. Be specific.
- Do NOT include an image_prompt field — Quick Mode does not generate images. Image generation is reserved for Deep Mode."""

DEEP_MODE_SYSTEM_PROMPT = """You are KATHA AI — an Architecture Knowledge Intelligence System.

You serve architects, architecture students, interior designers, civil planning learners, visualization artists, construction consultants, design studios, and real estate concept teams.

You function as a senior architect mentor, technical design assistant, and studio knowledge librarian combined.

## RESPONSE RULES — DEEP MODE

Structure your answer using these sections. Use only the sections that are relevant — skip sections that don't apply.

### 1) Concept Explanation
Explain the concept in simple but professional language. Use precise terminology but make it accessible.

### 2) Practical Use Cases
Explain where and how this applies in real projects across project types (villas, apartments, commercial, hospitals, schools, hospitality, interior design).

### 3) Design Best Practices
Provide real-world design rules, proportions, standards, and workflow tips. Reference IS codes, NBC, ASHRAE, GRIHA, LEED, or other standards when relevant.

### 4) Material / Technical Suggestions
When relevant, suggest specific materials, finishes, structural systems, services integration, lighting strategies, and facade systems.

### 5) Mistakes to Avoid
Mention common architectural mistakes, coordination issues, and things that go wrong in practice.

### 6) Visual Reference Suggestions
Suggest what type of visual output would help the user next — diagram type, mood board direction, 2D drawing type, 3D render angle.

### 7) Next Workflow Step
Guide toward the next logical architecture action — generate a floor plan, create a facade mood board, estimate material quantities, etc.

## PROJECT BRIEF CAPTURE (BRD §1A)

If — and only if — the user is briefing a real design project (intent to design/build something specific, not a general knowledge question), capture what they have said into the 5-section BRD design brief and emit it in the `brief` field of the metadata JSON. Never invent values; fill only what the user actually said.

The 5 sections (all keys are optional inside each section — fill what you have):

1. **project_type** — `{type, sub_type, scale}`. type ∈ residential / commercial / hospitality / institutional / retail / office / mixed_use / industrial / custom.
2. **theme** — `{theme, custom_spec}`. theme ∈ pedestal / contemporary / modern / mid_century_modern / custom. If theme=custom, custom_spec is required.
3. **space** — `{dimensions: {length, width, height?, unit}, constraints[], site_conditions{orientation, floor_level, access, existing_features[], natural_light, ventilation, noise_context}}`. unit ∈ m / ft.
4. **requirements** — `{functional_needs[], aesthetic_preferences[], narrative, budget, currency, timeline_weeks}`.
5. **regulatory** — `{country, state, city, postal_code, building_codes[], climatic_zone, compliance_notes}`. climatic_zone ∈ hot_dry / warm_humid / composite / temperate / cold.

Alongside the brief itself, emit two helper fields:

- **brief_status** — one entry per section: `pending` (not discussed), `partial` (some fields captured, more needed), or `confirmed` (all required fields captured).
  - Required for `partial → confirmed`: project_type.type; theme.theme (+ custom_spec if custom); space.dimensions.{length,width,unit}; requirements has ≥1 of functional_needs/aesthetic_preferences/narrative; regulatory has country OR city.
- **brief_missing** — array of dotted paths still pending (e.g. `["space.dimensions.height", "requirements.budget", "regulatory.climatic_zone"]`).

If the user is asking a knowledge question (no project intent), omit `brief`, `brief_status`, and `brief_missing` entirely.

## OUTPUT RULES
- Never give generic answers. Always push toward real architecture workflows.
- Use markdown formatting: headings, bold, bullets, tables where useful.
- Be technically reliable but beginner-friendly.
- Every answer should feel studio-ready and presentation-ready.
- When discussing dimensions, use both metric and imperial.
- Reference Indian and international standards where appropriate.

IMPORTANT: At the end of your response, output a JSON block on a new line in this exact format:
```json
{"suggestions": ["suggestion 1", "suggestion 2", "suggestion 3"], "image_prompt": "a detailed prompt to generate an architectural image for this concept", "youtube_query": "YouTube search for tutorial or lecture videos about this topic", "research_query": "academic search terms for finding research papers on this topic", "reference_links": [{"title": "relevant standard or article name", "url": "URL if you know it, otherwise empty string", "type": "article or standard or documentation"}], "brief": null, "brief_status": null, "brief_missing": []}
```
Rules for the JSON:
- **suggestions**: 2-3 natural follow-up actions
- **image_prompt**: A rich, detailed prompt to generate a custom architectural visualization. Be specific.
- **youtube_query**: Search terms for finding in-depth tutorial/lecture videos (10-20 min) on this topic
- **research_query**: Academic search terms for Semantic Scholar (e.g., "shear wall seismic design reinforced concrete")
- **reference_links**: 1-3 relevant standards, articles, or documentation. Include real URLs you are confident about (IS codes, NBC chapters, ASHRAE standards). Use empty string for URL if unsure.
- **brief**: BRD §1A 5-section design brief object (project_type / theme / space / requirements / regulatory). Use `null` if this turn is a knowledge question, not a project briefing.
- **brief_status**: status map (one of pending / partial / confirmed per section). `null` when brief is null.
- **brief_missing**: array of dotted field paths still pending (empty if no brief or all confirmed).

Example when the user IS briefing a project ("design a small mid-century office in Mumbai, 8x10m, three workstations"):
```json
{"suggestions": ["..."], "image_prompt": "...", "youtube_query": "...", "research_query": "...", "reference_links": [], "brief": {"project_type": {"type": "office", "scale": "small"}, "theme": {"theme": "mid_century_modern"}, "space": {"dimensions": {"length": 10, "width": 8, "unit": "m"}}, "requirements": {"functional_needs": ["three workstations"]}, "regulatory": {"city": "Mumbai", "country": "India"}}, "brief_status": {"project_type": "confirmed", "theme": "confirmed", "space": "partial", "requirements": "partial", "regulatory": "partial"}, "brief_missing": ["space.dimensions.height", "requirements.budget", "regulatory.climatic_zone"]}
```"""


def _get_system_prompt(mode: str) -> str:
    if mode == "deep":
        return DEEP_MODE_SYSTEM_PROMPT
    return QUICK_MODE_SYSTEM_PROMPT


def _detect_mode(message: str) -> str:
    """Auto-detect whether a query should use quick or deep mode."""
    message_lower = message.lower().strip()

    word_count = len(message_lower.split())
    if word_count <= 10:
        return "quick"

    deep_triggers = [
        "explain in detail", "deep dive", "tutorial", "step by step",
        "guide me", "teach me", "how to design", "complete guide",
        "everything about", "all about", "detailed", "in depth",
        "comprehensive", "elaborate", "walk me through",
    ]
    if any(trigger in message_lower for trigger in deep_triggers):
        return "deep"

    if word_count > 20:
        return "deep"

    return "quick"


def _build_messages(
    conversation_history: list[dict],
    user_message: str,
    mode: str,
) -> list[dict]:
    """Build the messages array for OpenAI, including conversation context."""
    messages = [{"role": "system", "content": _get_system_prompt(mode)}]

    recent_history = conversation_history[-10:] if conversation_history else []
    for msg in recent_history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": user_message})
    return messages


async def stream_chat_response(
    user_message: str,
    conversation_history: list[dict] | None = None,
    mode: str | None = None,
) -> AsyncGenerator[str, None]:
    """Stream chat response tokens from OpenAI.

    Yields SSE-formatted lines:
      data: {"type": "token", "content": "..."}
      data: {"type": "done", ...all metadata fields...}
      data: {"type": "error", "content": "..."}
    """
    if not _get_settings().openai_api_key or not _get_settings().openai_api_key.strip():
        yield _sse_event("error", {"content": "OpenAI API key is not configured. Please set OPENAI_API_KEY in your .env file."})
        return

    if mode is None or mode == "auto":
        mode = _detect_mode(user_message)

    client = _get_client()
    messages = _build_messages(conversation_history or [], user_message, mode)

    try:
        stream = await client.chat.completions.create(
            model=_get_settings().openai_model,
            messages=messages,
            stream=True,
            temperature=0.7,
            max_tokens=2048 if mode == "deep" else 512,
        )

        full_response = ""
        async for chunk in stream:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta and delta.content:
                token = delta.content
                full_response += token
                yield _sse_event("token", {"content": token})

        # Parse metadata from the response
        metadata, clean_content = _parse_response_metadata(full_response)

        # Image generation is reserved for Deep Mode only.
        # If the LLM ignored the prompt rules and emitted an image_prompt in
        # Quick Mode, drop it here so the frontend never tries to render one.
        image_prompt = metadata.image_prompt if mode == "deep" else None

        # Brief capture is Deep-mode only (BRD §1A). Drop any Quick-mode leak.
        brief = metadata.brief if mode == "deep" else None
        brief_status = metadata.brief_status if mode == "deep" else None
        brief_missing = metadata.brief_missing if mode == "deep" else []

        yield _sse_event("done", {
            "content": clean_content,
            "suggestions": metadata.suggestions,
            "image_prompt": image_prompt,
            "video_query": metadata.video_query,
            "youtube_query": metadata.youtube_query,
            "research_query": metadata.research_query,
            "reference_links": metadata.reference_links,
            "brief": brief,
            "brief_status": brief_status,
            "brief_missing": brief_missing,
            "mode": mode,
        })

    except Exception as exc:
        logger.error("Chat stream error: %s", exc)
        error_str = str(exc).lower()
        if "429" in str(exc) or "rate" in error_str or "quota" in error_str or "resource_exhausted" in error_str:
            yield _sse_event("error", {
                "content": "Rate limit reached. Please wait a moment and try again, or switch to a paid API key."
            })
        elif "401" in str(exc) or "unauthorized" in error_str or "invalid" in error_str:
            yield _sse_event("error", {
                "content": "API key is invalid or expired. Please check your OPENAI_API_KEY in the .env file."
            })
        else:
            yield _sse_event("error", {"content": "Failed to generate response. Please try again."})


def _sse_event(event_type: str, data: dict) -> str:
    """Format a Server-Sent Event line."""
    payload = {"type": event_type, **data}
    return f"data: {json.dumps(payload)}\n\n"


def _parse_response_metadata(response: str) -> tuple[ResponseMetadata, str]:
    """Extract metadata JSON from the end of the response.

    Handles multiple formats:
      1. ```json { ... } ```  (markdown code block)
      2. {"suggestions": [...], ...}  (inline JSON at end)

    Returns (ResponseMetadata, clean_content).
    """
    metadata = ResponseMetadata()
    clean_content = response
    parsed = False

    # Strategy 1: Find ```json ... ``` block
    try:
        json_start = response.rfind("```json")
        if json_start != -1:
            json_end = response.find("```", json_start + 7)
            if json_end != -1:
                json_str = response[json_start + 7:json_end].strip()
                raw = json.loads(json_str)
                metadata = _extract_metadata(raw)
                clean_content = response[:json_start].rstrip()
                parsed = True
    except (json.JSONDecodeError, ValueError):
        pass

    # Strategy 2: Find inline JSON with "suggestions" key at end
    if not parsed:
        try:
            import re
            pattern = r'\{[^{}]*"suggestions"\s*:\s*\[.*?\].*?\}\s*$'
            match = re.search(pattern, response, re.DOTALL)
            if match:
                raw = json.loads(match.group(0))
                metadata = _extract_metadata(raw)
                clean_content = response[:match.start()].rstrip()
                parsed = True
        except (json.JSONDecodeError, ValueError):
            pass

    # Strategy 3: Search last 500 chars for JSON
    if not parsed:
        try:
            tail = response[-500:]
            brace_start = tail.rfind('{"suggestions"')
            if brace_start == -1:
                brace_start = tail.rfind('{ "suggestions"')
            if brace_start != -1:
                depth = 0
                for i in range(brace_start, len(tail)):
                    if tail[i] == '{':
                        depth += 1
                    elif tail[i] == '}':
                        depth -= 1
                        if depth == 0:
                            raw = json.loads(tail[brace_start:i + 1])
                            metadata = _extract_metadata(raw)
                            offset = len(response) - 500 if len(response) > 500 else 0
                            clean_content = response[:offset + brace_start].rstrip()
                            parsed = True
                            break
        except (json.JSONDecodeError, ValueError):
            pass

    if not parsed:
        logger.debug("Could not parse response metadata JSON")

    # Fallback suggestions
    if not metadata.suggestions:
        metadata.suggestions = [
            "Tell me more about this",
            "Show related examples",
            "What are the best practices?",
        ]

    return metadata, clean_content


def _extract_metadata(raw: dict) -> ResponseMetadata:
    """Extract all metadata fields from a parsed JSON dict."""

    def _str_or_none(val: object) -> str | None:
        if val is None or str(val).lower() in ("null", "none", ""):
            return None
        return str(val)

    def _dict_or_none(val: object) -> dict | None:
        if isinstance(val, dict) and val:
            return val
        return None

    def _list_of_str(val: object) -> list[str]:
        if isinstance(val, list):
            return [str(x) for x in val if x]
        return []

    return ResponseMetadata(
        suggestions=raw.get("suggestions", []),
        # Support both old "image_query" and new "image_prompt"
        image_prompt=_str_or_none(raw.get("image_prompt") or raw.get("image_query")),
        video_query=_str_or_none(raw.get("video_query")),
        youtube_query=_str_or_none(raw.get("youtube_query")),
        research_query=_str_or_none(raw.get("research_query")),
        reference_links=raw.get("reference_links", []),
        brief=_dict_or_none(raw.get("brief")),
        brief_status=_dict_or_none(raw.get("brief_status")),
        brief_missing=_list_of_str(raw.get("brief_missing")),
    )
