"""Shared types across the corpus pipeline.

Why a dedicated types module?
-----------------------------
The extractors, chunker, ingester, and retriever all speak in
``Document`` / ``ExtractedPage`` shapes. Putting the dataclasses in
a leaf module keeps everyone free of circular imports.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


class ExtractionError(RuntimeError):
    """Raised when an extractor cannot turn the input into pages."""


@dataclass
class ExtractedPage:
    """One page of source content + the citation hooks the chunker
    needs to attribute later chunks correctly."""

    page: int  # 1-based — matches PDF readers + how humans cite ("page 12")
    text: str
    section_hint: str = ""
    """Most-recent heading detected on this page; the chunker uses it
    when the chunk doesn't carry its own heading."""

    extra: dict[str, Any] = field(default_factory=dict)
    """Format-specific bag — for PDF: ``{"width": ..., "height": ...}``."""


@dataclass
class Document:
    """A whole extracted document, ready to chunk + embed.

    The fields reflect the citation contract: every chunk we eventually
    insert must be able to point back to ``(jurisdiction, title,
    edition, page, section)``.
    """

    source_id: str
    title: str
    source_type: str = "pdf"  # pdf | text | markdown | catalog | textbook
    jurisdiction: str = ""
    publisher: str = ""
    edition: str = ""
    language: str = "en"
    effective_from: Optional[str] = None
    effective_to: Optional[str] = None
    pages: list[ExtractedPage] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_pages(self) -> int:
        return len(self.pages)
