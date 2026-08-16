"""Shared header helpers for the document exporters (pdf / docx / pptx / html).

One source of truth for the dossier subtitle so every format reads the same:
leads with the DESIGN's own title (not a reused/stale project name), skips an
empty room type and the None×None×None dims a massing design carries, and shows
a clean date rather than a raw ISO timestamp.
"""
from __future__ import annotations


def human_date(iso: str | None) -> str:
    """Raw ISO timestamp → a clean 'DD Mon YYYY'."""
    if not iso:
        return "—"
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(iso)).strftime("%d %b %Y")
    except Exception:
        return str(iso)[:10]


def dossier_title(meta: dict) -> str:
    """The design's display name — its own prompt, capitalised, else the project
    name. Used as the dossier lead everywhere."""
    lead = str(meta.get("design_title") or meta.get("project_name") or "Design").strip() or "Design"
    return lead[:1].upper() + lead[1:]


def dossier_meta_line(meta: dict) -> str:
    """The subtitle WITHOUT the title — room type · theme · dims · date. Use
    where the design title is already shown as the heading (e.g. the HTML h1),
    so it isn't repeated."""
    parts: list[str] = []
    rt = meta.get("room_type")
    if rt and str(rt) not in ("—", "None", ""):
        parts.append(str(rt).replace("_", " ").title())
    if meta.get("theme"):
        parts.append(f"Theme: {meta['theme']}")
    dims = meta.get("dimensions_m") or {}
    length, width, height = dims.get("length"), dims.get("width"), dims.get("height")
    if all(isinstance(v, (int, float)) for v in (length, width, height)):
        parts.append(f"{length} × {width} × {height} m")
    parts.append(f"Generated {human_date(meta.get('generated_at'))}")
    return "  ·  ".join(parts)


def dossier_subtitle(meta: dict) -> str:
    """One clean subtitle line: the design title + the meta line. Used where the
    heading is a fixed brand (e.g. 'KATHA Design Dossier')."""
    return f"{dossier_title(meta)}  ·  {dossier_meta_line(meta)}"
