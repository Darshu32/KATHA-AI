"""Stage 6 extractors — turn source bytes into structured pages."""

from app.corpus.extractors.pdf import extract_pdf
from app.corpus.extractors.plain_text import extract_plain_text
from app.corpus.extractors.types import (
    Document,
    ExtractedPage,
    ExtractionError,
)

__all__ = [
    "Document",
    "ExtractedPage",
    "ExtractionError",
    "extract_pdf",
    "extract_plain_text",
]
