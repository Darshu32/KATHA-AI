"""Theme lookup tools (Stage 4A).

Surface KATHA's theme rule packs to the LLM as structured tools. The
agent reaches for these whenever a user mentions a style ("modern",
"mid-century", "pedestal") or asks "what themes do you have?".

Both tools are read-only — no audit footprint, no DB writes.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from app.agents.tool import ToolContext, tool
from app.services.themes import (
    get_theme,
    list_published_themes,
)


# ─────────────────────────────────────────────────────────────────────
# lookup_theme
# ─────────────────────────────────────────────────────────────────────


class LookupThemeInput(BaseModel):
    slug_or_alias: str = Field(
        description=(
            "Theme slug or any registered alias. Examples: 'modern', "
            "'mid_century_modern', 'mcm', 'pedestal', 'plinth', "
            "'contemporary', 'custom'."
        ),
        max_length=64,
    )


class LookupThemeOutput(BaseModel):
    found: bool
    slug_or_alias_queried: str
    rule_pack: Optional[dict[str, Any]] = None
    """The full rule pack — includes display_name, era, proportions,
    material_palette, hardware, colour_palette, ergonomic_targets,
    signature_moves, dos, donts. ``None`` when not found."""


@tool(
    name="lookup_theme",
    description=(
        "Fetch the parametric rule pack for a design theme by slug or "
        "alias. Returns palette, hardware tier, ergonomic targets, "
        "signature moves, and dos/donts. Use whenever the user names a "
        "style — never assume theme content from memory; this is the "
        "source of truth."
    ),
    timeout_seconds=10.0,
)
async def lookup_theme(
    ctx: ToolContext,
    input: LookupThemeInput,
) -> LookupThemeOutput:
    pack = await get_theme(ctx.session, input.slug_or_alias)
    return LookupThemeOutput(
        found=pack is not None,
        slug_or_alias_queried=input.slug_or_alias,
        rule_pack=pack,
    )


# ─────────────────────────────────────────────────────────────────────
# list_themes
# ─────────────────────────────────────────────────────────────────────


class ListThemesInput(BaseModel):
    """No parameters — just lists every published theme."""


class ThemeSummary(BaseModel):
    slug: str
    display_name: str
    era: Optional[str] = None
    description: Optional[str] = None


class ListThemesOutput(BaseModel):
    themes: list[ThemeSummary]
    count: int


@tool(
    name="list_themes",
    description=(
        "List every theme available in the KATHA catalog (published "
        "only). Returns slug + display name + era for each. Use this "
        "when the user asks 'what themes do you have' or before "
        "suggesting a theme they might not know about."
    ),
    timeout_seconds=8.0,
)
async def list_themes(
    ctx: ToolContext,
    input: ListThemesInput,
) -> ListThemesOutput:
    rows = await list_published_themes(ctx.session)
    return ListThemesOutput(
        themes=[
            ThemeSummary(
                slug=r["slug"],
                display_name=r["display_name"],
                era=r.get("era"),
                description=r.get("description"),
            )
            for r in rows
        ],
        count=len(rows),
    )
