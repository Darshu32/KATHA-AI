"""PDF extractor — PyMuPDF wrapper.

The wrapper is deliberately thin:

1. Open the PDF from bytes.
2. Walk pages, capture text + the most recent heading-like line so
   chunks downstream can use it as a fallback section anchor.
3. Close the document, return :class:`Document`.

Why PyMuPDF
-----------
- Preserves the page model — important for "what page is this?"
  citations.
- Handles a wider range of malformed PDFs than ``pypdf``.
- Fast (C-backed): a 1000-page NBC takes a few seconds.

We import PyMuPDF lazily so the rest of the codebase + tests using
synthetic plain-text fixtures don't need it on the import path.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.corpus.extractors.types import (
    Document,
    ExtractedPage,
    ExtractionError,
)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Heading detection
# ─────────────────────────────────────────────────────────────────────


# Heuristic patterns for headings we care about in code books:
#   "Part 4 ..." / "PART 4 ..." / "Chapter 5 ..." / "§3.2.1 ..."
#   "Section 503" / "5.3.1 ..." / "Annex A"
_HEADING_PATTERNS = [
    re.compile(r"^\s*part\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*chapter\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*section\s+\d+", re.IGNORECASE),
    re.compile(r"^\s*annex\s+[A-Z]", re.IGNORECASE),
    re.compile(r"^\s*§\s*\d"),
    re.compile(r"^\s*\d+(\.\d+){1,3}\s+[A-Z]"),
]


def _looks_like_heading(line: str) -> bool:
    """Cheap heuristic — does this line read like a section heading?"""
    line = (line or "").strip()
    if not line or len(line) > 200:
        return False
    return any(p.match(line) for p in _HEADING_PATTERNS)


def _extract_section_hint(text: str, fallback: str) -> str:
    """Find the last heading-like line in this page's text."""
    last = ""
    for raw_line in (text or "").splitlines():
        if _looks_like_heading(raw_line):
            last = raw_line.strip()
    return last or fallback


# ─────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────


def extract_pdf(
    *,
    source_id: str,
    title: str,
    payload: bytes,
    jurisdiction: str = "",
    publisher: str = "",
    edition: str = "",
    language: str = "en",
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
) -> Document:
    """Extract a PDF byte payload into a :class:`Document`.

    Empty payload → :class:`ExtractionError`. Page-level extraction
    failures are caught and recorded as a page with ``text=""`` so
    the rest of the document still indexes.
    """
    if not payload:
        raise ExtractionError("PDF payload is empty")

    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover — guarded in prod
        raise ExtractionError(
            "PyMuPDF is not installed — run "
            "`pip install pymupdf` to enable PDF extraction."
        ) from exc

    try:
        doc = fitz.open(stream=payload, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError(f"PyMuPDF could not open PDF: {exc}") from exc

    pages: list[ExtractedPage] = []
    rolling_section = ""

    try:
        for page_index in range(doc.page_count):
            page_no = page_index + 1
            try:
                page = doc.load_page(page_index)
                text = page.get_text("text") or ""
                width = float(page.rect.width or 0)
                height = float(page.rect.height or 0)
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "PyMuPDF failed on page %d of %s: %s",
                    page_no, source_id, exc,
                )
                pages.append(ExtractedPage(page=page_no, text="", extra={"error": str(exc)}))
                continue

            section_hint = _extract_section_hint(text, fallback=rolling_section)
            if section_hint:
                rolling_section = section_hint

            pages.append(
                ExtractedPage(
                    page=page_no,
                    text=text,
                    section_hint=rolling_section,
                    extra={"width": width, "height": height},
                )
            )
    finally:
        doc.close()

    return Document(
        source_id=source_id,
        title=title,
        source_type="pdf",
        jurisdiction=jurisdiction,
        publisher=publisher,
        edition=edition,
        language=language,
        effective_from=effective_from,
        effective_to=effective_to,
        pages=pages,
    )
