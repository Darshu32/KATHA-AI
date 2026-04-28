"""Plain-text / markdown brief importer.

Pulls signals from a free-form design brief: budget, timeline, room
type, dimensions, style preferences, materials, style cues. The LLM
ingestion stage uses these as anchors when mapping to the design
brief schema.
"""

from __future__ import annotations

import re
from typing import Any


_BUDGET_RE = re.compile(
    r"(?:budget|cost|spend|allocate|allocation)[\s:~₹\$€£]*"
    r"([\d.,]+)\s*(crore|cr|lakh|lac|k|thousand|million|m|mn)?",
    re.IGNORECASE,
)
_TIMELINE_RE = re.compile(
    r"(?:within|in|over|by|deadline|complete in|delivery|ship in)\s+"
    r"(\d{1,3})\s*(day|days|week|weeks|month|months)",
    re.IGNORECASE,
)
_DIM_RE = re.compile(
    r"(\d{1,4}(?:\.\d+)?)\s*(?:[x×]|by)\s*(\d{1,4}(?:\.\d+)?)"
    r"(?:\s*(?:[x×]|by)\s*(\d{1,4}(?:\.\d+)?))?\s*(mm|cm|m|ft|feet|in|inch|inches|sqft|sqm)?",
    re.IGNORECASE,
)
_ROOM_KEYWORDS = (
    "bedroom", "living room", "kitchen", "bathroom", "office",
    "conference room", "restaurant", "retail", "hotel room", "gym",
    "classroom", "dining room", "study",
)
_STYLE_KEYWORDS = (
    "japandi", "scandinavian", "minimalist", "industrial", "art deco",
    "mid-century", "mid century", "biophilic", "rustic", "contemporary",
    "modern", "traditional", "wabi-sabi", "boho", "luxe",
)
_MATERIAL_KEYWORDS = (
    "walnut", "oak", "teak", "ash", "rubberwood", "mdf", "ply", "plywood",
    "brass", "stainless steel", "mild steel", "aluminium", "aluminum",
    "linen", "leather", "wool", "cotton", "boucle", "bouclé", "velvet",
    "marble", "granite", "terrazzo", "concrete",
)


def _find_keywords(text: str, vocab: tuple[str, ...]) -> list[str]:
    lower = text.lower()
    return [k for k in vocab if k in lower]


def _detect_brief_signals(text: str) -> dict[str, Any]:
    budgets: list[dict] = []
    for m in _BUDGET_RE.finditer(text):
        budgets.append({"raw": m.group(0).strip(), "value": m.group(1), "unit": (m.group(2) or "").lower()})
        if len(budgets) >= 6:
            break
    timelines: list[dict] = []
    for m in _TIMELINE_RE.finditer(text):
        timelines.append({"raw": m.group(0).strip(), "value": int(m.group(1)), "unit": m.group(2).lower()})
        if len(timelines) >= 6:
            break
    dims: list[dict] = []
    for m in _DIM_RE.finditer(text):
        a, b, c, unit = m.group(1), m.group(2), m.group(3), (m.group(4) or "").lower()
        dims.append({
            "raw": m.group(0).strip(),
            "values": [float(a), float(b)] + ([float(c)] if c else []),
            "unit": unit or "unknown",
        })
        if len(dims) >= 12:
            break
    return {
        "budgets": budgets,
        "timelines": timelines,
        "dimensions": dims,
        "rooms_mentioned": _find_keywords(text, _ROOM_KEYWORDS),
        "styles_mentioned": _find_keywords(text, _STYLE_KEYWORDS),
        "materials_mentioned": _find_keywords(text, _MATERIAL_KEYWORDS),
    }


def parse(filename: str, payload: bytes) -> dict[str, Any]:
    text = payload.decode("utf-8", errors="ignore")
    signals = _detect_brief_signals(text)
    word_count = len(re.findall(r"\b\w+\b", text))
    return {
        "format": "text",
        "filename": filename,
        "size_bytes": len(payload),
        "summary": (
            f"Plain text brief: {word_count} words; "
            f"{len(signals['budgets'])} budget mention(s); "
            f"{len(signals['dimensions'])} dimension hint(s); "
            f"{len(signals['rooms_mentioned'])} room cue(s)."
        ),
        "extracted": {
            "word_count": word_count,
            "text_excerpt": text[:3000],
            "brief_signals": signals,
        },
        "warnings": [] if text.strip() else ["File body is empty."],
    }
