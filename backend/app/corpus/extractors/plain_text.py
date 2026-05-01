"""Plain-text + markdown extractor.

For test fixtures, hand-converted code excerpts, and the rare
documents we actually have as text. The extractor splits on form
feeds (``\\f``) into "pages" — convention used by tools that emit
per-page text dumps. With no form feeds, the whole input is one
"page" so citations still resolve.

Why a separate extractor instead of feeding text into the PDF path?
-------------------------------------------------------------------
PyMuPDF expects valid PDF bytes. Round-tripping text → PDF →
extraction would be wasteful and brittle. The plain-text path
keeps the test surface fast and dependency-free.
"""

from __future__ import annotations

from typing import Optional

from app.corpus.extractors.pdf import _extract_section_hint
from app.corpus.extractors.types import (
    Document,
    ExtractedPage,
    ExtractionError,
)


def extract_plain_text(
    *,
    source_id: str,
    title: str,
    text: str,
    source_type: str = "text",
    jurisdiction: str = "",
    publisher: str = "",
    edition: str = "",
    language: str = "en",
    effective_from: Optional[str] = None,
    effective_to: Optional[str] = None,
) -> Document:
    """Build a :class:`Document` from plain text.

    Form-feed (``\\f``) characters split the input into pages. With
    no form feeds, the result is a single page.
    """
    if text is None:
        raise ExtractionError("Text payload is None")

    raw_pages = text.split("\f") if "\f" in text else [text]

    pages: list[ExtractedPage] = []
    rolling_section = ""
    for page_index, body in enumerate(raw_pages):
        page_no = page_index + 1
        body = body or ""
        section_hint = _extract_section_hint(body, fallback=rolling_section)
        if section_hint:
            rolling_section = section_hint
        pages.append(
            ExtractedPage(
                page=page_no,
                text=body,
                section_hint=rolling_section,
            )
        )

    return Document(
        source_id=source_id,
        title=title,
        source_type=source_type,
        jurisdiction=jurisdiction,
        publisher=publisher,
        edition=edition,
        language=language,
        effective_from=effective_from,
        effective_to=effective_to,
        pages=pages,
    )
