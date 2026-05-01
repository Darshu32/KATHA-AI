"""Architect-fingerprint extractor.

Reads the architect's design graphs + tool-usage audit events and
emits a structured fingerprint:

- Preferred themes (count + share).
- Preferred materials (count + share).
- Preferred palette hexes (where graphs carry colour metadata).
- Typical room dimensions (median across projects).
- Tool-usage patterns (which tools called most, share of total).

Privacy
-------
The extractor itself doesn't read the User row — privacy gating
lives in :mod:`app.workers.memory_extraction`. Pass
``learning_enabled=True`` only after confirming the architect's
flag is set.

Failure semantics
-----------------
Empty input → empty :class:`ArchitectFingerprint` (project_count=0).
Never raises on missing fields — the extractor is defensive against
old / partial graph_data shapes.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Optional


@dataclass
class ArchitectFingerprint:
    """Structured output of the per-user extractor."""

    user_id: str
    project_count: int = 0
    preferred_themes: list[dict[str, Any]] = field(default_factory=list)
    preferred_materials: list[dict[str, Any]] = field(default_factory=list)
    preferred_palette_hexes: list[str] = field(default_factory=list)
    typical_room_dimensions_m: dict[str, float] = field(default_factory=dict)
    tool_usage: list[dict[str, Any]] = field(default_factory=list)
    last_project_at: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "project_count": self.project_count,
            "preferred_themes": list(self.preferred_themes),
            "preferred_materials": list(self.preferred_materials),
            "preferred_palette_hexes": list(self.preferred_palette_hexes),
            "typical_room_dimensions_m": dict(self.typical_room_dimensions_m),
            "tool_usage": list(self.tool_usage),
            "last_project_at": self.last_project_at,
        }


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _normalise_string(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().lower()
    return text or None


def _pluck_theme(graph: dict[str, Any]) -> Optional[str]:
    style = graph.get("style") or {}
    if isinstance(style, dict):
        return _normalise_string(style.get("primary"))
    return _normalise_string(style)


def _pluck_room_dims(graph: dict[str, Any]) -> tuple[Optional[float], Optional[float], Optional[float]]:
    room = graph.get("room") or (graph.get("spaces") or [{}])[0] or {}
    dims = room.get("dimensions") or {}

    def _num(v: Any) -> Optional[float]:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return _num(dims.get("length")), _num(dims.get("width")), _num(dims.get("height"))


def _pluck_materials(graph: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for m in graph.get("materials") or []:
        if not isinstance(m, dict):
            continue
        for key in ("name", "category"):
            v = _normalise_string(m.get(key))
            if v:
                out.append(v)
                break
    # Also pull material from each object — captures cases where
    # the top-level materials list is empty but objects carry it.
    for o in graph.get("objects") or []:
        if not isinstance(o, dict):
            continue
        v = _normalise_string(o.get("material"))
        if v:
            out.append(v)
    return out


def _pluck_palette(graph: dict[str, Any]) -> list[str]:
    """Pull #hex entries from common palette shapes.

    Looks at ``graph['style']['palette']`` (a list of hex strings or
    ``{"hex": "#..."}`` dicts) and ``graph['palette']`` (same shape).
    """
    found: list[str] = []
    candidates: list[Any] = []
    style = graph.get("style") or {}
    if isinstance(style, dict):
        candidates.extend(style.get("palette") or [])
    candidates.extend(graph.get("palette") or [])

    for entry in candidates:
        if isinstance(entry, dict):
            hex_val = entry.get("hex") or entry.get("color")
        else:
            hex_val = entry
        if not isinstance(hex_val, str):
            continue
        hex_val = hex_val.strip().lower()
        if hex_val.startswith("#") and len(hex_val) in (4, 7, 9):
            found.append(hex_val)
    return found


def _share(counter: Counter[str], total: int) -> list[dict[str, Any]]:
    if total <= 0:
        return []
    return [
        {"name": name, "count": count, "share": round(count / total, 4)}
        for name, count in counter.most_common(20)
    ]


# ─────────────────────────────────────────────────────────────────────
# Public extractor
# ─────────────────────────────────────────────────────────────────────


def extract_architect_fingerprint(
    *,
    user_id: str,
    design_graphs: Iterable[dict[str, Any]],
    tool_calls: Optional[Iterable[dict[str, Any]]] = None,
    last_project_at: Optional[str] = None,
) -> ArchitectFingerprint:
    """Compute the architect's fingerprint.

    Parameters
    ----------
    user_id:
        The architect's user id — copied verbatim onto the result.
    design_graphs:
        Iterable of design graph dicts (one per project's latest
        version, typically). Order doesn't matter.
    tool_calls:
        Optional iterable of audit-event-style records: each is a
        dict with at least ``{"action": "tool_call", "after": {"tool": str}}``.
        Other shapes are tolerated; missing entries → empty
        ``tool_usage``.
    last_project_at:
        ISO timestamp of the most-recent project's update, used by
        the agent's system prompt to phrase how recent the data is.
    """
    graphs = [g for g in (design_graphs or []) if isinstance(g, dict)]
    project_count = len(graphs)

    if project_count == 0 and not tool_calls:
        return ArchitectFingerprint(user_id=user_id)

    # Themes.
    theme_counter: Counter[str] = Counter()
    material_counter: Counter[str] = Counter()
    palette_counter: Counter[str] = Counter()
    lengths: list[float] = []
    widths: list[float] = []
    heights: list[float] = []

    for graph in graphs:
        theme = _pluck_theme(graph)
        if theme:
            theme_counter[theme] += 1

        for mat in _pluck_materials(graph):
            material_counter[mat] += 1

        for hex_val in _pluck_palette(graph):
            palette_counter[hex_val] += 1

        l, w, h = _pluck_room_dims(graph)
        if l is not None:
            lengths.append(l)
        if w is not None:
            widths.append(w)
        if h is not None:
            heights.append(h)

    typical_dims: dict[str, float] = {}
    if lengths:
        typical_dims["length"] = round(median(lengths), 3)
    if widths:
        typical_dims["width"] = round(median(widths), 3)
    if heights:
        typical_dims["height"] = round(median(heights), 3)

    # Tool usage.
    tool_counter: Counter[str] = Counter()
    for event in (tool_calls or []):
        if not isinstance(event, dict):
            continue
        if (event.get("action") or "") != "tool_call":
            continue
        after = event.get("after") or {}
        tool_name = _normalise_string(after.get("tool")) if isinstance(after, dict) else None
        if not tool_name:
            tool_name = _normalise_string(event.get("tool"))
        if tool_name:
            tool_counter[tool_name] += 1
    total_tool_calls = sum(tool_counter.values())

    return ArchitectFingerprint(
        user_id=user_id,
        project_count=project_count,
        preferred_themes=_share(theme_counter, project_count),
        preferred_materials=_share(material_counter, sum(material_counter.values())),
        preferred_palette_hexes=[h for h, _ in palette_counter.most_common(8)],
        typical_room_dimensions_m=typical_dims,
        tool_usage=_share(tool_counter, total_tool_calls),
        last_project_at=last_project_at,
    )
