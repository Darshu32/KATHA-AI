"""Stage 6 chunker — split a Document into citable chunks.

Chunking strategy
-----------------
- **Target ~500 tokens, max 1500 tokens** per chunk (4-chars-per-token
  heuristic).
- **15% overlap** between adjacent chunks — gives the retriever
  redundancy at chunk borders so a query that hits a sentence
  spanning two chunks can still match.
- **Page boundaries are soft** — a chunk can span 2 pages if both
  paragraphs are short. We record ``(page, page_end)`` so the
  citation points at the actual range.
- **Section anchors propagate** — each chunk carries the most-recent
  heading detected before/within it (from
  :attr:`ExtractedPage.section_hint`).

Why we don't reuse the project-memory chunker
---------------------------------------------
That chunker (Stage 5B) is structured-data-aware — it formats
labelled fields ("Theme: ...", "Materials: ..."). Source documents
are prose with citation hooks (page numbers, section labels) we
must preserve. Two different shapes, two different chunkers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.corpus.extractors.types import Document, ExtractedPage


# Heuristics — same as the project memory chunker's defaults.
CHARS_PER_TOKEN = 4
TARGET_TOKENS = 500
MAX_TOKENS = 1500
OVERLAP_RATIO = 0.15  # 15% overlap with the previous chunk


@dataclass
class Chunk:
    """One chunk ready for embedding + DB insertion."""

    content: str
    page: int
    page_end: int
    section: str
    chunk_index: int
    total_chunks: int
    token_estimate: int
    extra: dict[str, Any] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _estimate_tokens(s: str) -> int:
    return max(1, len(s) // CHARS_PER_TOKEN)


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n")


def _paragraphs(page_text: str) -> list[str]:
    """Split a page into paragraphs. Empty/whitespace blocks dropped."""
    text = (page_text or "").strip()
    if not text:
        return []
    return [p.strip() for p in _PARAGRAPH_BREAK.split(text) if p.strip()]


# ─────────────────────────────────────────────────────────────────────
# Public chunker
# ─────────────────────────────────────────────────────────────────────


def chunk_document(
    doc: Document,
    *,
    target_tokens: int = TARGET_TOKENS,
    max_tokens: int = MAX_TOKENS,
    overlap_ratio: float = OVERLAP_RATIO,
) -> list[Chunk]:
    """Turn a :class:`Document` into a list of :class:`Chunk`.

    Walks pages in order, accumulating paragraphs into a buffer. When
    the buffer crosses ``target_tokens`` we flush it to a chunk; if a
    single paragraph exceeds ``max_tokens``, the chunker emits the
    current buffer and then sentence-splits the giant paragraph.

    The ``page`` / ``page_end`` fields on the returned chunks track
    the smallest-to-largest page touched by that chunk's content.

    ``overlap_ratio`` between 0 and 1 — fraction of the previous
    chunk's tail that prepends to the next chunk. Set to 0 to
    disable.
    """
    if overlap_ratio < 0 or overlap_ratio >= 1:
        raise ValueError(f"overlap_ratio must be in [0, 1), got {overlap_ratio}")

    target_chars = target_tokens * CHARS_PER_TOKEN
    max_chars = max_tokens * CHARS_PER_TOKEN

    # Buffer state.
    buf_parts: list[str] = []
    buf_chars = 0
    buf_page_start = 0
    buf_page_end = 0
    buf_section = ""

    chunks: list[Chunk] = []

    def _flush() -> None:
        nonlocal buf_parts, buf_chars, buf_page_start, buf_page_end, buf_section
        if not buf_parts:
            return
        text = "\n\n".join(buf_parts).strip()
        if not text:
            buf_parts = []
            buf_chars = 0
            return
        chunks.append(
            Chunk(
                content=text,
                page=buf_page_start or buf_page_end or 0,
                page_end=buf_page_end or buf_page_start or 0,
                section=buf_section,
                chunk_index=0,            # set later when we know totals
                total_chunks=0,
                token_estimate=_estimate_tokens(text),
            )
        )
        # Prepare overlap for the next chunk: keep the last N chars
        # of the just-flushed text in the new buffer.
        if overlap_ratio > 0 and len(text) > 0:
            tail_len = int(len(text) * overlap_ratio)
            # Round to a reasonable boundary if possible.
            tail = text[-tail_len:] if tail_len > 0 else ""
            buf_parts = [tail] if tail else []
            buf_chars = len(tail)
        else:
            buf_parts = []
            buf_chars = 0
        # Page tracking starts fresh — re-set when next paragraph appended.
        buf_page_start = 0
        buf_page_end = 0
        # Section anchor persists into the next chunk if no new heading
        # appears yet.

    def _append(text: str, page: int, section_hint: str) -> None:
        nonlocal buf_parts, buf_chars, buf_page_start, buf_page_end, buf_section
        if not text:
            return
        if buf_page_start == 0:
            buf_page_start = page
        buf_page_end = page
        if section_hint:
            buf_section = section_hint
        if buf_parts:
            buf_chars += 2  # for the "\n\n" join later
        buf_parts.append(text)
        buf_chars += len(text)

    def _split_giant(text: str) -> list[str]:
        """Sentence-split a paragraph that's bigger than max_chars."""
        # Cheap sentence split — periods + line breaks.
        parts: list[str] = []
        current: list[str] = []
        current_len = 0
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if not sentence:
                continue
            if current_len + len(sentence) + 1 > max_chars and current:
                parts.append(" ".join(current))
                current = []
                current_len = 0
            current.append(sentence)
            current_len += len(sentence) + 1
        if current:
            parts.append(" ".join(current))
        return parts

    for page in doc.pages:
        page_no = page.page
        section_hint = page.section_hint

        for para in _paragraphs(page.text):
            para_chars = len(para)

            if para_chars > max_chars:
                # Flush current buffer first so the giant paragraph
                # gets its own chunks.
                _flush()
                pieces = _split_giant(para)
                for piece in pieces:
                    _append(piece, page=page_no, section_hint=section_hint)
                    if buf_chars >= target_chars:
                        _flush()
                continue

            # Would adding this paragraph cross the soft target?
            if buf_chars + para_chars > target_chars and buf_parts:
                _flush()

            _append(para, page=page_no, section_hint=section_hint)

    _flush()

    # Set chunk_index + total_chunks now we know the grand total.
    total = len(chunks)
    for i, c in enumerate(chunks):
        c.chunk_index = i
        c.total_chunks = total

    return chunks
