"""Canonical project-type definitions.

Single source of truth for everything the system says about each
project type: its enum slug, its display label, its description, the
starter prompts the empty-state surfaces, and the visual hint the
image-generation prompt is prefixed with.

Keeping all of these in one file means the frontend's selector, the
backend's image_service prompt prefix, the knowledge_injector segment
mapping, and the public ``GET /api/v1/project-types`` endpoint never
drift from each other.

If you need to add a new type:
  1. Add an entry to PROJECT_TYPE_DEFINITIONS below.
  2. Add the corresponding value to ProjectTypeEnum in
     ``app.models.brief`` (the canonical enum).
  3. Add a knowledge segment mapping in
     ``app.services.knowledge_injector._SEGMENT_BY_PROJECT_TYPE``.

The enum + this list MUST stay in sync; the public route validates
this on import.
"""

from __future__ import annotations

from typing import TypedDict

from app.models.brief import ProjectTypeEnum


class ProjectTypeDef(TypedDict):
    slug: str  # matches ProjectTypeEnum value
    label: str  # UI label
    description: str  # one-line description for tooltips / metadata
    starter_prompts: list[str]  # canvas empty-state suggestions
    visual_hint: str  # prefixed into image-gen prompt
    is_primary: bool  # primary 6 buttons vs overflow
    sort_order: int  # ascending; primaries first by sort, then overflow


PROJECT_TYPE_DEFINITIONS: list[ProjectTypeDef] = [
    {
        "slug": "residential",
        "label": "Residential",
        "description": (
            "Homes, apartments, villas — domestic scale, family use, "
            "long-term inhabitation."
        ),
        "starter_prompts": [
            "A 3 BHK apartment kitchen with an island, walnut cabinetry, and pendant lighting",
            "A master bedroom with a walk-in wardrobe and a reading nook by the window",
            "A compact 1 BHK living-cum-dining for a young couple, warm minimal palette",
        ],
        "visual_hint": (
            "residential interior — domestic scale, warm and lived-in, "
            "family-use furnishings, soft natural light"
        ),
        "is_primary": True,
        "sort_order": 10,
    },
    {
        "slug": "commercial",
        "label": "Commercial",
        "description": (
            "Public-facing commercial spaces — banks, showrooms, "
            "co-working, mixed-tenant fit-outs."
        ),
        "starter_prompts": [
            "A modern bank branch interior with welcoming reception, glazed cabins, brand-aligned palette",
            "A retail showroom for a premium electronics brand, clean sightlines, feature wall",
            "A corporate co-working floor with hot-desks, phone booths, and a central café",
        ],
        "visual_hint": (
            "commercial interior — public-facing scale, durable finishes, "
            "brand-aligned palette, even ambient lighting"
        ),
        "is_primary": True,
        "sort_order": 20,
    },
    {
        "slug": "hospitality",
        "label": "Hospitality",
        "description": (
            "Hotels, restaurants, bars, spas — guest experience, "
            "premium materials, durable for high traffic."
        ),
        "starter_prompts": [
            "A boutique hotel lobby with a dramatic reception desk, lounge seating, and live edge wood",
            "A 70-cover restaurant interior with banquette seating and warm pendant lighting",
            "A spa treatment room with calming earth tones and indirect lighting",
        ],
        "visual_hint": (
            "hospitality interior — hotel / restaurant aesthetic, "
            "guest-flow ergonomics, mood lighting, premium materials"
        ),
        "is_primary": True,
        "sort_order": 30,
    },
    {
        "slug": "office",
        "label": "Office",
        "description": (
            "Workplace — open-plan floors, executive cabins, "
            "boardrooms, breakout zones."
        ),
        "starter_prompts": [
            "An open-plan office floor for 60 people with collaboration zones and meeting rooms",
            "An executive cabin with a meeting table, accent wall, and acoustic treatment",
            "A 12-person boardroom with a long table and integrated AV",
        ],
        "visual_hint": (
            "office interior — workplace ergonomics, modular furniture, "
            "task lighting, acoustic treatment, clean professional palette"
        ),
        "is_primary": True,
        "sort_order": 40,
    },
    {
        "slug": "retail",
        "label": "Retail",
        "description": (
            "Storefronts, showrooms, merchandising — display-led, "
            "feature lighting, customer journey."
        ),
        "starter_prompts": [
            "A flagship apparel store with central island display and dramatic lighting",
            "A jewellery showroom with secure display cases, warm metallics, and a private viewing alcove",
            "A bakery cafe with a glass display counter and casual seating",
        ],
        "visual_hint": (
            "retail interior — merchandise-led, dramatic feature lighting, "
            "clear customer sightlines, brand-aligned fixtures"
        ),
        "is_primary": True,
        "sort_order": 50,
    },
    {
        "slug": "institutional",
        "label": "Institutional",
        "description": (
            "Civic, educational, healthcare, cultural — accessible, "
            "durable, calm; long lifecycle."
        ),
        "starter_prompts": [
            "A modern library reading room with double-height ceilings and wood acoustic panels",
            "A primary school classroom for 30 students with flexible seating",
            "A waiting hall for a clinic — calm, accessible, with natural light",
        ],
        "visual_hint": (
            "institutional interior — civic / educational / healthcare scale, "
            "accessible, durable, calm and welcoming"
        ),
        "is_primary": True,
        "sort_order": 60,
    },
    {
        "slug": "mixed_use",
        "label": "Mixed-use",
        "description": (
            "Buildings combining residential, commercial, retail, or "
            "office on different floors."
        ),
        "starter_prompts": [
            "Ground-floor retail with apartments above — facade and lobby for a 6-storey building",
            "A live-work loft with a workspace nook integrated into a 1 BHK plan",
            "A community-facing ground floor café with offices on the floor above",
        ],
        "visual_hint": (
            "mixed-use building — public ground floor with private upper "
            "floors, transitional materiality"
        ),
        "is_primary": False,
        "sort_order": 70,
    },
    {
        "slug": "industrial",
        "label": "Industrial",
        "description": (
            "Factories, warehouses, workshops — utilitarian, "
            "high-bay, durable industrial finishes."
        ),
        "starter_prompts": [
            "A small factory floor with mezzanine office, cleanroom partition, and material flow",
            "A logistics warehouse with high-bay racking and a packing station",
            "A craft brewery taproom with the production floor visible behind glass",
        ],
        "visual_hint": (
            "industrial interior — utilitarian, exposed structure, "
            "high-bay or workshop scale, durable industrial finishes"
        ),
        "is_primary": False,
        "sort_order": 80,
    },
    {
        "slug": "custom",
        "label": "Custom",
        "description": (
            "Anything outside the above taxonomy — interpret the "
            "prompt's spirit literally."
        ),
        "starter_prompts": [
            "Describe what you want — KATHA will treat the type as bespoke and generate accordingly.",
        ],
        "visual_hint": "bespoke project — interpret the prompt's spirit literally",
        "is_primary": False,
        "sort_order": 90,
    },
]


# Sanity-check at import: every enum value has a definition + vice versa.
_DEFINED_SLUGS = {d["slug"] for d in PROJECT_TYPE_DEFINITIONS}
_ENUM_VALUES = {e.value for e in ProjectTypeEnum}
assert _DEFINED_SLUGS == _ENUM_VALUES, (
    f"PROJECT_TYPE_DEFINITIONS / ProjectTypeEnum drift: "
    f"in-list-only={_DEFINED_SLUGS - _ENUM_VALUES}, "
    f"in-enum-only={_ENUM_VALUES - _DEFINED_SLUGS}"
)


def visual_hint_for(slug: str | None) -> str:
    """Return the visual hint string for a slug, or empty if unknown."""
    if not slug:
        return ""
    for d in PROJECT_TYPE_DEFINITIONS:
        if d["slug"] == slug.lower().strip():
            return d["visual_hint"]
    return ""


def list_definitions(*, primary_only: bool = False) -> list[ProjectTypeDef]:
    """Return all definitions, sorted ascending. Pass primary_only=True
    to filter to the six primary buttons."""
    items = [
        d for d in PROJECT_TYPE_DEFINITIONS
        if not primary_only or d["is_primary"]
    ]
    return sorted(items, key=lambda d: d["sort_order"])
