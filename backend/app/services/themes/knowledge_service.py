"""DB-backed theme accessors — replaces the legacy sync ``themes.get``.

Stage 3A migrates the cost-engine + agent-tool path to read themes
from the DB. Other (~25) services still import the legacy
``app.knowledge.themes`` module synchronously; they'll migrate
gradually in later stages.

Public entry points
-------------------
- :func:`get_theme`                — full rule pack for a slug/alias.
- :func:`describe_theme_for_prompt` — multi-line prompt block.
- :func:`list_published_themes`     — name + slug list for menus.

Output shape matches what ``app.knowledge.themes.get(name)`` returned —
the cost-engine prompt expects the same keys ("display_name",
"material_palette", "hardware", …). When the DB is empty (eg. fresh
dev box pre-seed) we fall back to the legacy literal so the cost
engine never crashes due to missing data.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import themes as legacy_themes
from app.repositories.themes import ThemeRepository


def _flatten_for_legacy_shape(row: dict[str, Any]) -> dict[str, Any]:
    """Re-attach ``display_name`` to the rule pack so callers get the
    same shape the legacy ``themes.get`` returned.

    Stage 3A stores ``display_name`` as a top-level column for indexing,
    but downstream consumers (cost-engine prompt, tool outputs) expect
    it inside the rule pack. We keep both surfaces in sync here.
    """
    pack = dict(row.get("rule_pack") or {})
    pack["display_name"] = row.get("display_name") or pack.get("display_name") or row.get("slug")
    if row.get("era") and "era" not in pack:
        pack["era"] = row["era"]
    return pack


async def get_theme(
    session: AsyncSession,
    slug_or_alias: str,
    *,
    when: Optional[datetime] = None,
) -> Optional[dict[str, Any]]:
    """Return the rule pack for a theme, alias-aware, with legacy fallback.

    Resolution order:
      1. Active published theme in the DB matching slug or alias.
      2. Legacy ``app.knowledge.themes.get`` literal.
      3. ``None`` if neither has it.
    """
    if not slug_or_alias:
        return None

    repo = ThemeRepository(session)
    row = await repo.get_active_by_slug(slug_or_alias, when=when)
    if row is not None:
        return _flatten_for_legacy_shape(row)

    # Fallback — keeps fresh-DB / dev environments from breaking.
    return legacy_themes.get(slug_or_alias)


async def list_published_themes(
    session: AsyncSession,
    *,
    when: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Compact list (slug + display_name + era) of published themes.

    Useful for admin UIs and the agent's "what themes are available?"
    introspection. Legacy fallback: when the DB is empty, returns the
    legacy preset list.
    """
    repo = ThemeRepository(session)
    rows = await repo.list_active(status="published", when=when)
    if rows:
        return [
            {
                "slug": r["slug"],
                "display_name": r["display_name"],
                "era": r["era"],
                "description": r["description"],
            }
            for r in rows
        ]

    # Fallback for fresh-DB scenarios.
    return [
        {
            "slug": slug,
            "display_name": pack.get("display_name") or slug.replace("_", " ").title(),
            "era": pack.get("era"),
            "description": None,
        }
        for slug, pack in legacy_themes.THEMES.items()
    ]


async def describe_theme_for_prompt(
    session: AsyncSession,
    slug_or_alias: str,
    *,
    when: Optional[datetime] = None,
) -> str:
    """Multi-line theme description for LLM prompt injection.

    Same format as the legacy sync :func:`app.knowledge.themes.describe_for_prompt`.
    Stage 6 (RAG) may extend this with citation footers.
    """
    pack = await get_theme(session, slug_or_alias, when=when)
    if not pack:
        return f"(No parametric rules found for theme '{slug_or_alias}'.)"

    lines = [f"Theme: {pack.get('display_name') or slug_or_alias}"]
    mats = pack.get("material_palette") or {}
    if mats.get("primary"):
        lines.append(f"- Primary materials: {', '.join(mats['primary'])}")
    if mats.get("secondary"):
        lines.append(f"- Secondary materials: {', '.join(mats['secondary'])}")
    if mats.get("upholstery"):
        lines.append(f"- Upholstery: {', '.join(mats['upholstery'])}")
    if pack.get("colour_palette"):
        lines.append(f"- Colour palette: {', '.join(pack['colour_palette'])}")
    hw = pack.get("hardware") or {}
    if hw:
        lines.append(
            f"- Hardware: {hw.get('style', '')} "
            f"({hw.get('material', '')}, {hw.get('finish', '')})"
        )
    ergo = pack.get("ergonomic_targets") or {}
    if ergo:
        ergo_bits = [f"{k}={v}" for k, v in ergo.items()]
        lines.append(f"- Ergonomic targets: {', '.join(ergo_bits)}")
    if pack.get("signature_moves"):
        lines.append(f"- Signature moves: {'; '.join(pack['signature_moves'])}")
    if pack.get("dos"):
        lines.append(f"- Do: {'; '.join(pack['dos'])}")
    if pack.get("donts"):
        lines.append(f"- Don't: {'; '.join(pack['donts'])}")
    return "\n".join(lines)
