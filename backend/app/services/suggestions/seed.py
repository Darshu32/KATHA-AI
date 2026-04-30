"""Stage 3F — suggestion-chip seed builder.

Translates the legacy hardcoded ``DEFAULT_SUGGESTIONS`` array (in
``frontend/components/chat/suggestion-chips.tsx``) into DB rows.

The frontend will fall back to the same set if the API ever returns
empty, so admin can safely deactivate any of these without breaking
the UX.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4


# Mirrors the original frontend default — kept here as the canonical
# source of truth for the seed migration. After Stage 3F lands, the
# frontend's hardcoded array is reduced to a minimal "last-ditch
# fallback" copy of one or two chips for true offline-mode rendering.
_DEFAULT_CHIPS: list[dict[str, Any]] = [
    {
        "slug": "modern_villa_facade_ideas",
        "label": "Modern villa facade ideas",
        "prompt": (
            "Suggest modern villa facade design ideas with clean lines, "
            "large glass panels, and natural materials"
        ),
        "tags": ["facade", "modern", "villa"],
        "weight": 100,
    },
    {
        "slug": "sustainable_material_options",
        "label": "Sustainable material options",
        "prompt": (
            "What are the best sustainable and eco-friendly building "
            "materials for residential architecture?"
        ),
        "tags": ["sustainability", "materials"],
        "weight": 95,
    },
    {
        "slug": "vastu_living_room_layout",
        "label": "Vastu living room layout",
        "prompt": (
            "Explain Vastu Shastra principles for designing a living room "
            "layout with proper orientation and element placement"
        ),
        "tags": ["vastu", "living_room", "india"],
        "weight": 90,
    },
    {
        "slug": "natural_lighting_tips",
        "label": "Natural lighting tips",
        "prompt": (
            "What are the best architectural strategies to maximize natural "
            "lighting in residential spaces?"
        ),
        "tags": ["lighting", "passive_design"],
        "weight": 85,
    },
]


def build_suggestion_seed_rows() -> list[dict[str, Any]]:
    """Every Stage 3F suggestion seed row, ready for ``op.bulk_insert``."""
    return [
        {
            "id": uuid4().hex,
            "slug": chip["slug"],
            "label": chip["label"],
            "prompt": chip["prompt"],
            "description": "Seeded from frontend default suggestion array.",
            "contexts": ["chat_empty_hero"],
            "weight": int(chip.get("weight", 100)),
            "status": "published",
            "tags": chip.get("tags") or None,
            "source": "seed:frontend.DEFAULT_SUGGESTIONS",
        }
        for chip in _DEFAULT_CHIPS
    ]
