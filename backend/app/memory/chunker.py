"""Per-source-type chunking — turn artefacts into searchable text.

The agent doesn't search dicts — it searches *text*. Each source kind
(design version, spec bundle, cost engine, drawing/diagram) needs a
small pure function that produces one or more strings, each:

- A bounded number of tokens (we use a 4-chars-per-token heuristic
  so we don't take a tokeniser dependency).
- Self-contained — readable in isolation when surfaced by the recall
  tool ("the kitchen has a 1.8m walnut island, brass hardware, …").
- Loosely structured so the embedder picks up labels (Materials:,
  Theme:, etc.).

Why text and not JSON
---------------------
``text-embedding-3-small`` is trained on prose. Embedding raw JSON
gives noisier vectors than embedding a paragraph that the LLM will
also be happy to read back. The trade-off: we lose schema fidelity
in the recall view; the agent can re-fetch the source row by id
when it needs the structured form.

Token budget
------------
- Soft target: ~500 tokens per chunk (≈2000 chars).
- Hard cap: 1500 tokens (≈6000 chars) — over that we split.
- Empty / whitespace-only chunks are filtered out at the indexer.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


# Heuristic token estimate. OpenAI's tokeniser averages ~4 chars per
# token for English; spec sheets are denser so we accept some slack.
CHARS_PER_TOKEN = 4
TARGET_TOKENS = 500
MAX_TOKENS = 1500


@dataclass
class Chunk:
    """One piece of indexable text plus metadata for the row."""

    content: str
    chunk_index: int = 0
    total_chunks: int = 1
    token_estimate: int = 0
    extra: dict[str, Any] | None = None


def _estimate_tokens(s: str) -> int:
    return max(1, len(s) // CHARS_PER_TOKEN)


# ─────────────────────────────────────────────────────────────────────
# Generic text splitter
# ─────────────────────────────────────────────────────────────────────


def chunk_text(
    text: str,
    *,
    target_tokens: int = TARGET_TOKENS,
    max_tokens: int = MAX_TOKENS,
) -> list[Chunk]:
    """Split arbitrary text into one-or-more chunks.

    Splits on paragraph boundaries first (``\\n\\n``), then on lines
    if a paragraph alone exceeds the cap. We don't recurse into
    sentence splitting — anything single-sentence above ``max_tokens``
    is rare enough to leave alone (it'll just be a slightly large
    embedding input, still well under the 8K-token API limit).

    Returns an empty list for empty / whitespace-only input.
    """
    text = (text or "").strip()
    if not text:
        return []

    target_chars = target_tokens * CHARS_PER_TOKEN
    max_chars = max_tokens * CHARS_PER_TOKEN

    # Fast path — small inputs become one chunk.
    if len(text) <= max_chars:
        return [
            Chunk(
                content=text,
                chunk_index=0,
                total_chunks=1,
                token_estimate=_estimate_tokens(text),
            )
        ]

    # Split into paragraphs first, then merge greedily.
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    buffer: list[str] = []
    buffer_chars = 0

    def _flush() -> None:
        if buffer:
            chunks.append("\n\n".join(buffer))

    for para in paragraphs:
        para_chars = len(para)
        if para_chars > max_chars:
            # A single paragraph too large — split on lines.
            _flush()
            buffer = []
            buffer_chars = 0
            line_buf: list[str] = []
            line_chars = 0
            for line in para.splitlines():
                if line_chars + len(line) + 1 > max_chars and line_buf:
                    chunks.append("\n".join(line_buf))
                    line_buf = []
                    line_chars = 0
                line_buf.append(line)
                line_chars += len(line) + 1
            if line_buf:
                chunks.append("\n".join(line_buf))
            continue

        if buffer_chars + para_chars + 2 > target_chars and buffer:
            _flush()
            buffer = []
            buffer_chars = 0
        buffer.append(para)
        buffer_chars += para_chars + 2

    _flush()

    total = len(chunks)
    return [
        Chunk(
            content=c,
            chunk_index=i,
            total_chunks=total,
            token_estimate=_estimate_tokens(c),
        )
        for i, c in enumerate(chunks)
    ]


# ─────────────────────────────────────────────────────────────────────
# Per-source-type chunkers
# ─────────────────────────────────────────────────────────────────────


def _safe(value: Any, default: str = "—") -> str:
    """Render a value as a stable short string; empty / None → default."""
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            text = str(value)
    else:
        text = str(value)
    text = text.strip()
    return text or default


def chunk_design_version(
    graph_data: dict[str, Any],
    *,
    project_name: str = "",
    version_label: str = "",
) -> list[Chunk]:
    """Render a design-graph version into searchable text.

    The output reads like a one-page summary: room dims, theme,
    objects (type + dimensions + material), materials list. The
    LLM reading a recall hit should immediately see what design
    state we're talking about.
    """
    room = graph_data.get("room") or (graph_data.get("spaces") or [{}])[0] or {}
    dims = room.get("dimensions") or {}
    objects = list(graph_data.get("objects") or [])
    materials = list(graph_data.get("materials") or [])
    style = graph_data.get("style") or {}
    style_primary = style.get("primary") if isinstance(style, dict) else None

    header_lines = [
        f"Design version: {version_label or '(unspecified)'}",
        f"Project: {_safe(project_name)}",
        f"Theme: {_safe(style_primary)}",
        f"Room: {_safe(room.get('type') or graph_data.get('room_type'))}",
        f"Room dimensions: length={_safe(dims.get('length'))}m, "
        f"width={_safe(dims.get('width'))}m, "
        f"height={_safe(dims.get('height'))}m",
        f"Object count: {len(objects)}",
        f"Material count: {len(materials)}",
    ]
    header = "\n".join(header_lines)

    obj_lines: list[str] = []
    for o in objects[:60]:  # cap to avoid runaway sizes
        d = o.get("dimensions") or {}
        obj_lines.append(
            f"- {_safe(o.get('type'))} \"{_safe(o.get('name'), default='')}\" "
            f"id={_safe(o.get('id'))} "
            f"L={_safe(d.get('length'))} W={_safe(d.get('width'))} "
            f"H={_safe(d.get('height'))} mat={_safe(o.get('material'))}"
        )

    mat_lines: list[str] = []
    for m in materials[:40]:
        mat_lines.append(
            f"- {_safe(m.get('name'))} ({_safe(m.get('category'))}) "
            f"finish={_safe(m.get('finish'))}"
        )

    body_parts = [header]
    if obj_lines:
        body_parts.append("Objects:\n" + "\n".join(obj_lines))
    if mat_lines:
        body_parts.append("Materials:\n" + "\n".join(mat_lines))

    return chunk_text("\n\n".join(body_parts))


def chunk_spec_bundle(
    bundle: dict[str, Any],
    *,
    project_name: str = "",
) -> list[Chunk]:
    """Render a Stage-4D spec bundle (material + manufacturing + mep).

    We surface each section as its own paragraph so the chunker can
    naturally split a long bundle into per-section chunks.
    """
    meta = bundle.get("meta") or {}
    parts = [
        f"Spec bundle for: {_safe(project_name or meta.get('project_name'))}",
        f"Theme: {_safe(meta.get('theme'))}",
        f"Room: {_safe(meta.get('room_type'))}",
        f"Dimensions (m): {_safe(meta.get('dimensions_m'))}",
    ]

    for section_key in ("material", "manufacturing", "mep", "cost"):
        section = bundle.get(section_key)
        if section is None or section == {}:
            continue
        rendered = _safe(section)
        if len(rendered) > 600:
            rendered = rendered[:600] + "…"
        parts.append(f"{section_key.title()} spec:\n{rendered}")

    return chunk_text("\n\n".join(parts))


def chunk_cost_engine(
    cost_engine: dict[str, Any],
    *,
    pricing_snapshot_id: str = "",
) -> list[Chunk]:
    """Render a Stage-2 cost engine breakdown — totals + assumptions."""
    summary = cost_engine.get("summary") or {}
    overhead = cost_engine.get("overhead") or {}
    material = cost_engine.get("material_cost") or {}
    labor = cost_engine.get("labor_cost") or {}
    header = cost_engine.get("header") or {}

    lines = [
        f"Cost engine snapshot: {pricing_snapshot_id or '(none)'}",
        f"Project: {_safe(header.get('project'))}",
        f"Piece: {_safe(header.get('piece_name'))}",
        f"Theme: {_safe(header.get('theme'))}",
        f"City: {_safe(header.get('city'))} "
        f"(index {_safe(header.get('city_price_index'))})",
        f"Market: {_safe(header.get('market_segment'))}",
        f"Complexity: {_safe(header.get('complexity'))}",
        f"Total manufacturing cost (INR): "
        f"{_safe(cost_engine.get('total_manufacturing_cost_inr'))}",
        f"Material subtotal: {_safe(material.get('material_subtotal_inr'))} "
        f"({_safe(summary.get('material_pct_of_total'))}%)",
        f"Labor subtotal: {_safe(labor.get('labor_subtotal_inr'))} "
        f"({_safe(summary.get('labor_pct_of_total'))}%)",
        f"Overhead subtotal: {_safe(overhead.get('overhead_subtotal_inr'))} "
        f"({_safe(summary.get('overhead_pct_of_total'))}%)",
    ]

    assumptions = cost_engine.get("assumptions") or []
    if assumptions:
        lines.append("Assumptions:")
        for a in assumptions[:30]:
            lines.append(f"- {_safe(a)}")

    return chunk_text("\n".join(lines))


def chunk_drawing_or_diagram(
    spec: dict[str, Any],
    *,
    kind: str,
    title: str = "",
    theme: str = "",
) -> list[Chunk]:
    """Render the LLM-authored drawing/diagram spec into text.

    We index the *spec* (rationale, key dimensions, callouts, scale)
    rather than the SVG bytes — the SVG is non-textual and an
    embedder would gain nothing from it. The kind argument is the
    canonical id from the producing tool ("plan_view",
    "elevation_view", "concept_transparency", etc.).
    """
    parts = [
        f"{kind.replace('_', ' ').title()}: {_safe(title)}",
        f"Theme: {_safe(theme)}",
    ]

    # Surface a few well-known spec keys with stable labels.
    for key in (
        "scale",
        "scale_rationale",
        "sheet_narrative",
        "narrative",
        "rationale",
        "key_dimensions",
        "section_references",
        "material_zones",
        "stages",
        "signature_moves_in_play",
        "zone_assignments",
        "emphasis_points",
        "joinery_methods",
        "hardware_callouts",
        "detail_callouts",
        "cells",
        "watch_outs",
        "ranking",
    ):
        if key not in spec:
            continue
        value = spec[key]
        if value in (None, "", [], {}):
            continue
        rendered = _safe(value)
        if len(rendered) > 500:
            rendered = rendered[:500] + "…"
        parts.append(f"{key.replace('_', ' ').title()}: {rendered}")

    return chunk_text("\n\n".join(parts))
